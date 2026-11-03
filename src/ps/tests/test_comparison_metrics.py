"""对比展示数值与原始计数保持一致，指纹接口停用；不操作真实设备。"""
import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'web')]
import services,server

class ComparisonMetrics(unittest.TestCase):
    def test_metrics_preserve_shift_and_amplitude_without_classification(self):
        with tempfile.TemporaryDirectory()as folder:
            p=Path(folder)
            with patch.object(services,'PROJECT',p),patch.object(services,'WEB',p/'web'):
                c=services.Controller(json.loads((ROOT/'web/config.json').read_text()))
                w=services.FrameWriter('fe','fe_01',c.config,'pl',{})
                x=np.arange(65536);paths=[];original=[]
                for i,(position,amplitude)in enumerate([(17500,100),(17540,60)]):
                    counts=(1+4000*np.exp(-((x-10120)/4)**2)+amplitude*np.exp(-((x-position)/85)**2)).astype('uint32')
                    paths.append(w.save(i+1,x,counts,None).relative_to(p).as_posix());original.append(counts.copy())
                c.job={'id':'test','status':'idle'}
                with patch.object(c,'recognize_counts',side_effect=AssertionError('仅波形不可分类')):
                    c._compare(dict(paths=paths,recognize=False))
                rows=c.comparison['frames'];self.assertEqual(len(rows),2)
                self.assertEqual(rows[1]['metrics']['return_bin']-rows[0]['metrics']['return_bin'],40)
                self.assertGreater(rows[0]['metrics']['peak_ratio'],rows[1]['metrics']['peak_ratio'])
                for before,after in zip(original,c.comparison_frames):np.testing.assert_array_equal(before,after)
                self.assertEqual(c.comparison_plot('full')['y_max'],500)
                with patch.object(server,'controller',c):
                    self.assertEqual(server.app.test_client().post('/api/fingerprints/view',json={}).status_code,404)

if __name__=='__main__':unittest.main()
