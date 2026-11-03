"""无需历史工作目录的多点校准回归，只操作临时文件。"""
import sys,tempfile,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from live_ranging import LiveRangeCalibration

class Calibration(unittest.TestCase):
    def test_three_points_and_individual_delete(self):
        x=np.arange(65536)
        with tempfile.TemporaryDirectory()as folder:
            store=LiveRangeCalibration(folder,boot_id='test')
            context=dict(signature='test-config',bin_width_ps=8)
            points=[]
            for distance in (10,20,30):
                c=(2+5000*np.exp(-((x-10000)/5)**2)+100*np.exp(-((x-(17000+distance*10))/80)**2)).astype('uint32')
                points.append(store.capture_group([c]*10,distance,context))
            store.apply_multi()
            self.assertIsNotNone(store.profile())
            store.delete_point(points[1]['id'])
            self.assertEqual([p['distance_cm']for p in store.summary()['points']],[10,30])
            self.assertIsNone(store.profile())
            self.assertFalse((Path(folder)/points[1]['frame_file']).exists())
            self.assertTrue((Path(folder)/points[0]['frame_file']).is_file())

if __name__=='__main__':unittest.main()
