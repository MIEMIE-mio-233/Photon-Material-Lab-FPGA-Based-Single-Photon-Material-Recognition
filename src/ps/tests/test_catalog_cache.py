"""批次增量缓存与状态非阻塞回归，仅操作临时目录。"""
import unittest,tempfile,sys,threading,time,csv,os
from pathlib import Path
from unittest.mock import patch
ROOT=Path(os.environ.get('TDC_TEST_PROJECT', str(Path(__file__).resolve().parents[1])))
sys.path[:0]=[str(ROOT),str(ROOT/'web')]
import services

class CatalogCache(unittest.TestCase):
    def test_changed_batch_only_and_deleted_file_force(self):
        with tempfile.TemporaryDirectory()as temp,patch.object(services,'PROJECT',Path(temp)),patch.object(services,'WEB',Path(temp)/'web'):
            store=services.DataStore();cfg={'trig_freq_hz':100000,'trig_num':100000,'bin_width':3}
            bins=services.np.arange(65536);counts=services.np.zeros(65536,dtype='uint32')
            a=services.FrameWriter('fe','fe',cfg,'pl',{});b=services.FrameWriter('pp','pp',cfg,'pl',{})
            a.save(1,bins,counts,None);b.save(1,bins,counts,None)
            with patch.object(store,'_build_index',wraps=store._build_index)as build:
                self.assertEqual(store.index()['frame_count'],2);self.assertEqual(build.call_count,2)
                build.reset_mock();self.assertEqual(store.browser_index()['frame_count'],2);build.assert_not_called()
                a.save(2,bins,counts,None)
                self.assertEqual(store.index()['frame_count'],3);self.assertEqual(build.call_count,1)
                self.assertEqual(build.call_args.args[0],[a.manifest])
                (a.folder/'frame_0001.npy').unlink()
                self.assertEqual(store.index(force=True)['frame_count'],2)
            store.delete_run('dataset',b.run_id)
            self.assertEqual(store.index()['frame_count'],1)

    def test_status_does_not_wait_for_catalog_lock(self):
        with tempfile.TemporaryDirectory()as temp,patch.object(services,'PROJECT',Path(temp)),patch.object(services,'WEB',Path(temp)/'web'):
            store=services.DataStore();store.index();store.next_index_check=time.monotonic()+60
            held,release=threading.Event(),threading.Event()
            def block():
                with store.index_lock:held.set();release.wait(2)
            t=threading.Thread(target=block);t.start();self.assertTrue(held.wait(1))
            done=threading.Event();result=[]
            def state():result.append(store.status_index());done.set()
            reader=threading.Thread(target=state);reader.start()
            try:self.assertTrue(done.wait(.2),'状态请求被目录扫描阻塞')
            finally:release.set();t.join();reader.join()
            self.assertEqual(result[0]['frame_count'],0)

    def test_manifest_path_still_cannot_escape_batch(self):
        with tempfile.TemporaryDirectory()as temp,patch.object(services,'PROJECT',Path(temp)),patch.object(services,'WEB',Path(temp)/'web'):
            root=Path(temp);store=services.DataStore();run=root/'dataset/run_escape';run.mkdir()
            (root/'escape.npy').write_bytes(b'not a real frame')
            row=dict(csv_path='../../escape.npy',material_id='fe',specimen_id='fe',frame_index='1',bin_num='65536')
            with(run/'manifest.csv').open('w',newline='')as f:w=csv.DictWriter(f,fieldnames=list(row));w.writeheader();w.writerow(row)
            self.assertEqual(store.index()['frame_count'],0)

if __name__=='__main__':unittest.main()
