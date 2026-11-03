"""9维契约、CNN波形学习、光照元数据和历史演示同步；不访问硬件。"""
import json,sys,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'web')]
import train_material as t
import services
from feature_contract import model_features,reference_from_training,LEGACY_VERSION,LEGACY_NAMES
from cnn_models import TinyCNNClassifier,PortableCNN,export_cnn,sample,pack_cnn
from training_validation import split_data


class NewPipeline(unittest.TestCase):
    def test_peak_shift_and_legacy_boundary(self):
        x=np.arange(65536);c=(1+9000*np.exp(-((x-10120)/4)**2)+120*np.exp(-((x-17500)/90)**2)).astype('uint32')
        f,d=t.extract_features(c)
        self.assertEqual(len(f),9);self.assertEqual(f[8],d['return_bin'])
        metadata=dict(feature_version=t.FEATURE_VERSION,feature_names=t.FEATURE_NAMES,timing_reference_bin=17000.5)
        self.assertEqual(model_features(f,metadata)[8],d['return_bin']-17000.5)
        legacy=dict(feature_version=LEGACY_VERSION,feature_names=LEGACY_NAMES)
        np.testing.assert_array_equal(model_features(f,legacy),f[:8])
        with self.assertRaises(ValueError):model_features(f,dict(metadata,feature_names=t.FEATURE_NAMES[::-1]))
        self.assertEqual(sample(c,model_features(f,metadata),d['return_bin']).shape,(265,))

    def test_reference_only_uses_training_fe_15cm(self):
        data=SimpleNamespace(features=np.c_[np.zeros((4,8)),[100,102,900,500]],labels=np.array(['fe']*4),
                             details=[(None,dict(distance_cm=d),{}) for d in [15.,15.,15.,20.]])
        self.assertEqual(reference_from_training(data,[0,1]),(101.,'training_fe_15cm'))
        self.assertEqual(reference_from_training(data,[3]),(0.,'absolute_peak_fallback'))

    def test_cnn_learns_waveform_without_auxiliary_information(self):
        wave=np.zeros((16,256));wave[:8,35:43]=32;wave[8:,190:198]=32
        X=np.c_[np.zeros((16,9)),wave];labels=np.array(['a']*8+['b']*8)
        m=TinyCNNClassifier(epochs=100,learning_rate=.01).fit(X,labels)
        self.assertTrue((m.predict(X)==labels).all())
        self.assertLess(m.loss_curve_[-1],m.loss_curve_[0])
        meta=dict(feature_names=t.FEATURE_NAMES,feature_version=t.FEATURE_VERSION,model_type='TinyCNNClassifier')
        payload=export_cnn(m,meta);p=PortableCNN(payload)
        np.testing.assert_allclose(p.predict_proba(X),m.predict_proba(X),atol=0,rtol=0)
        self.assertLessEqual(len(pack_cnn(payload)),2048)
        payload['parameters'][0]=[[0]*4]
        with self.assertRaises(ValueError):PortableCNN(payload)

    def test_illumination_saved_without_changing_material_class(self):
        with tempfile.TemporaryDirectory() as folder:
            project=Path(folder)
            with patch.object(services,'PROJECT',project):
                config=json.loads((ROOT/'web/config.json').read_text())
                for light in ['shielded','partial','exposed']:
                    writer=services.FrameWriter('fe','fe_01',config,'pl',dict(distance_cm=15,sample_kind='material',illumination=light,experiment_round='round_02'))
                    writer.save(1,np.arange(65536),np.ones(65536,dtype='uint32'),None)
                    saved=json.loads((writer.root/'config.json').read_text())
                    self.assertEqual(saved['illumination'],light);self.assertEqual(saved['sample_kind'],'material')
                index=services.DataStore().index()
                self.assertEqual(index['training_materials'],['fe'])
                self.assertEqual({f['illumination'] for f in index['frames']},{'shielded','partial','exposed'})
                self.assertTrue(all(f['experiment_round']=='round_02' for f in index['frames']))

    def test_complete_round_holdout_covers_conditions(self):
        details=[];labels=[]
        for rnd in ['round_01','round_02','round_03']:
            for light in ['shielded','partial','exposed']:
                for material in ['a','b']:
                    for frame in range(2):
                        labels.append(material);details.append((None,dict(experiment_round=rnd,illumination=light,distance_cm=15,material_id=material,specimen_id=material,_run_key=rnd+light+material),{}))
        data=SimpleNamespace(labels=np.array(labels),groups=np.array(labels),frame_numbers=np.tile([1,2],18),details=details)
        tr,te,method=split_data(data)
        self.assertEqual(len(tr),24);self.assertEqual(len(te),12)
        self.assertTrue(all(details[i][1]['experiment_round']=='round_03' for i in te))
        self.assertIn('entire experiment round',method)

    def test_history_waits_for_display_and_has_minimum_interval(self):
        with tempfile.TemporaryDirectory() as folder:
            project=Path(folder)
            with patch.object(services,'PROJECT',project),patch.object(services,'WEB',project/'web'):
                c=services.Controller(json.loads((ROOT/'web/config.json').read_text()))
                c.store=SimpleNamespace(index=lambda:dict(materials=['fe'],frames=[dict(material='fe',path='dataset/frame.npy')]),
                    resolve_frame=lambda _:project/'dataset/frame.npy',read=lambda _:(np.arange(65536),np.ones(65536,dtype='uint32'),None))
                ready=threading.Event();published=[];original=c.publish_frame
                def publish(*args,**kwargs):
                    result=original(*args,**kwargs);published.append((time.monotonic(),result));ready.set();return result
                errors=[]
                def capture():
                    try:c._capture(dict(source='history',frames=2,recognize=False,interval_s=0,demo_sync=True))
                    except Exception as e:errors.append(e)
                with patch.object(c,'publish_frame',side_effect=publish):
                    worker=threading.Thread(target=capture);worker.start();self.assertTrue(ready.wait(2))
                    c.acknowledge_demo('expired');self.assertIsNone(c.demo_displayed_id)
                    time.sleep(.12);self.assertEqual(len(published),1)
                    c.acknowledge_demo(published[0][1]['result_id'])
                    deadline=time.monotonic()+3
                    while len(published)<2 and time.monotonic()<deadline:time.sleep(.02)
                    self.assertEqual(len(published),2)
                    self.assertGreaterEqual(published[1][0]-published[0][0],.98)
                    c.acknowledge_demo(published[1][1]['result_id']);worker.join(3)
                    self.assertFalse(worker.is_alive());self.assertEqual(errors,[])


if __name__=='__main__':unittest.main()
