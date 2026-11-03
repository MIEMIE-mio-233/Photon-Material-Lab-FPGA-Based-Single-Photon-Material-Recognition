// 一帧真实数据的C/RTL协同仿真；不访问真实板卡或激光器。
#include <stdint.h>
#include <fstream>
#include <string>
#include <cstdlib>
#include <cmath>
#include <iostream>
extern "C" void tdc_accelerator(const uint32_t*,const double*,double*,int,int,int,int,int,int,double);
static uint32_t histogram[65536];
static double model[1114240], result[88], expected[88];
int main() {
    const char *directory=std::getenv("TDC_TEST_DATA_DIR");
    if(!directory)return 1;
    std::string prefix=std::string(directory)+"/";
    // 元数据依次为：类别数、树数、节点数、模型类型、特征数、参数double数。
    int dimensions[6];
    double baseline=0;
    std::ifstream meta((prefix+"dimensions.bin").c_str(),std::ios::binary);
    std::ifstream counts((prefix+"histogram.bin").c_str(),std::ios::binary);
    std::ifstream parameters((prefix+"model.bin").c_str(),std::ios::binary);
    std::ifstream golden((prefix+"expected.bin").c_str(),std::ios::binary);
    std::ifstream reference((prefix+"baseline.bin").c_str(),std::ios::binary);
    if(!meta||!counts||!parameters||!golden||!reference)return 2;
    meta.read((char*)dimensions,sizeof(dimensions));
    if(!meta || dimensions[5]<1 || dimensions[5]>1114240)return 2;
    counts.read((char*)histogram,sizeof(histogram));
    parameters.read((char*)model,sizeof(double)*dimensions[5]);
    golden.read((char*)expected,sizeof(expected));
    reference.read((char*)&baseline,sizeof(baseline));
    if(!counts||!parameters||!golden||!reference)return 2;
    tdc_accelerator(histogram,model,result,65536,dimensions[0],dimensions[1],dimensions[2],dimensions[3],dimensions[4],baseline);
    for(int i=0;i<88;++i) {
        if(!std::isfinite(result[i])||std::fabs(result[i]-expected[i])>1e-12) {
            std::cerr<<"FAIL output["<<i<<"]="<<result[i]<<" expected="<<expected[i]<<"\n";
            return 3;
        }
    }
    std::cout<<"PASS: fixture features, peaks, scores and label\n";
    return 0;
}
