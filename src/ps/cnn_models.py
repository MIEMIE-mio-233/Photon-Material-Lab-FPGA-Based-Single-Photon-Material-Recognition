"""小型一维CNN：NumPy训练/便携推理，PL复用既有串行乘加器。

输入：256点面积归一化回波 + 9维统计特征；4个5点卷积核、ReLU、
8点平均池化、8神经元全连接、类别输出。卷积核参与反向传播训练，
不是在9个统计量上假装卷积，也不需要板端安装PyTorch。
"""
import numpy as np
from dense_models import softmax

FORMAT = 'tdc_tiny_cnn_v1'
WAVE_SIZE, POOL, CHANNELS, KERNEL, HIDDEN, AUX = 256, 8, 4, 5, 8, 9
INPUT_SIZE = AUX + WAVE_SIZE
SPEC = dict(window_start=-1024, window_length=2048, sum_pool=8,
            normalization='area_density_256_float32', padding='zero_same',
            conv_channels=4, kernel_size=5, average_pool=8, hidden=8)


def waveform(counts, echo):
    """从原始非负计数取窗，先整数求和再归一化，与HLS完全同序。"""
    counts = np.asarray(counts)
    if int(echo) < 1024 or int(echo)+1024 > len(counts):
        raise ValueError('CNN回波窗口超出直方图边界')
    window = counts[int(echo)-1024:int(echo)+1024].astype(np.uint64)
    groups = window.reshape(WAVE_SIZE, POOL).sum(axis=1, dtype=np.uint64)
    total = int(groups.sum(dtype=np.uint64))
    if total <= 0:
        raise ValueError('CNN回波窗口没有有效计数')
    return (groups.astype(np.float64)*WAVE_SIZE/total).astype(np.float32).astype(np.float64)


def sample(counts, features, echo):
    return np.r_[np.asarray(features, dtype=np.float32).astype(np.float64), waveform(counts, echo)]


class TinyCNNClassifier:
    """有界小网络，Adam仅使用训练数据；损失早停不接触外层测试集。"""
    def __init__(self, epochs=250, learning_rate=0.003, alpha=0.001, batch_size=32, random_state=42):
        self.epochs, self.learning_rate, self.alpha = epochs, learning_rate, alpha
        self.batch_size, self.random_state = batch_size, random_state

    @staticmethod
    def _patches(wave):
        padded = np.pad(wave, ((0,0),(2,2)))
        return np.stack([padded[:,i:i+WAVE_SIZE] for i in range(KERNEL)], axis=2)

    def _forward(self, samples, cache=False):
        samples = np.asarray(samples, dtype=np.float32).astype(np.float64)
        if samples.ndim!=2 or samples.shape[1]!=INPUT_SIZE or not np.isfinite(samples).all():
            raise ValueError('CNN输入必须为9维统计量加256点归一化回波')
        aux=(samples[:,:AUX]-self.mean)/self.scale
        patches=self._patches(samples[:,AUX:])
        wc,bc,w1,b1,w2,b2=self.parameters
        conv=np.einsum('nlk,kc->nlc',patches,wc,optimize=False)+bc
        pooled=np.maximum(conv,0).reshape(-1,WAVE_SIZE//POOL,POOL,CHANNELS).mean(axis=2)
        joined=np.concatenate([pooled.reshape(len(samples),-1),aux],axis=1)
        hidden=joined@w1+b1; logits=np.maximum(hidden,0)@w2+b2
        return (logits,(patches,conv,joined,hidden)) if cache else logits

    def fit(self, samples, labels):
        samples=np.asarray(samples,dtype=np.float32).astype(np.float64)
        self.classes_, targets=np.unique(labels,return_inverse=True)
        if len(self.classes_)<2 or len(self.classes_)>64 or samples.shape!=(len(labels),INPUT_SIZE):
            raise ValueError('小型CNN要求2–64类以及完整回波输入')
        self.mean=samples[:,:AUX].mean(axis=0);self.scale=samples[:,:AUX].std(axis=0)
        self.scale[self.scale<1e-12]=1.0
        rng=np.random.RandomState(self.random_state);c=len(self.classes_);inputs=128+AUX
        self.parameters=[rng.normal(0,np.sqrt(2/KERNEL),(KERNEL,CHANNELS)),np.zeros(CHANNELS),
            rng.normal(0,np.sqrt(2/inputs),(inputs,HIDDEN)),np.zeros(HIDDEN),
            rng.normal(0,np.sqrt(1/HIDDEN),(HIDDEN,c)),np.zeros(c)]
        moment=[np.zeros_like(w) for w in self.parameters];square=[np.zeros_like(w) for w in self.parameters]
        best_loss=np.inf;best=None;stale=0;step=0;self.loss_curve_=[]
        for epoch in range(int(self.epochs)):
            order=rng.permutation(len(samples))
            for offset in range(0,len(samples),int(self.batch_size)):
                ix=order[offset:offset+self.batch_size];logits,cache=self._forward(samples[ix],True)
                patches,conv,joined,hidden=cache;wc,bc,w1,b1,w2,b2=self.parameters
                delta=softmax(logits);delta[np.arange(len(ix)),targets[ix]]-=1;delta/=len(ix)
                dh=(delta@w2.T)*(hidden>0);dj=dh@w1.T
                dc=np.repeat(dj[:,:128].reshape(-1,32,CHANNELS)[:,:,None,:]/POOL,POOL,axis=2).reshape(-1,256,CHANNELS)*(conv>0)
                grads=[np.einsum('nlk,nlc->kc',patches,dc,optimize=False)+self.alpha*wc,dc.sum(axis=(0,1)),
                       joined.T@dh+self.alpha*w1,dh.sum(axis=0),np.maximum(hidden,0).T@delta+self.alpha*w2,delta.sum(axis=0)]
                step+=1
                for i,grad in enumerate(grads):
                    np.clip(grad,-5,5,out=grad)
                    moment[i]=.9*moment[i]+.1*grad;square[i]=.999*square[i]+.001*grad*grad
                    self.parameters[i]-=self.learning_rate*(moment[i]/(1-.9**step))/(np.sqrt(square[i]/(1-.999**step))+1e-8)
            prob=softmax(self._forward(samples));loss=float(-np.log(np.maximum(prob[np.arange(len(samples)),targets],1e-15)).mean()+self.alpha/2*sum(np.sum(w*w) for w in self.parameters[::2]))
            if not np.isfinite(loss):raise ValueError('CNN训练出现非有限损失')
            self.loss_curve_.append(loss)
            if loss<best_loss-1e-5:best_loss=loss;best=[w.copy() for w in self.parameters];stale=0
            else:stale+=1
            if (epoch+1)%50==0:print('CNN训练：第{}轮，训练损失{:.5f}'.format(epoch+1,loss),flush=True)
            if stale>=40:break
        self.parameters=best;self.n_iter_=len(self.loss_curve_);self.loss_=best_loss
        return self

    def decision_function(self,samples):return self._forward(samples)
    def predict_proba(self,samples):return softmax(self.decision_function(samples))
    def predict(self,samples):return self.classes_[np.argmax(self.decision_function(samples),axis=1)]


def export_cnn(model,metadata):
    payload=dict(metadata,format=FORMAT,class_names=list(map(str,model.classes_)),cnn_settings=SPEC,
                 mean=model.mean.tolist(),scale=model.scale.tolist(),
                 parameters=[w.tolist() for w in model.parameters],score_kind='model_probability')
    PortableCNN(payload)
    return payload


class PortableCNN(TinyCNNClassifier):
    def __init__(self,payload):
        if payload.get('format')!=FORMAT or payload.get('cnn_settings')!=SPEC:
            raise ValueError('CNN格式或回波预处理定义不匹配')
        self.classes_=np.asarray(payload['class_names']);c=len(self.classes_)
        self.mean=np.asarray(payload['mean'],dtype=float);self.scale=np.asarray(payload['scale'],dtype=float)
        self.parameters=[np.asarray(w,dtype=float) for w in payload['parameters']]
        shapes=[(5,4),(4,),(137,8),(8,),(8,c),(c,)]
        if not 2<=c<=64 or len(set(self.classes_))!=c or self.mean.shape!=(9,) or self.scale.shape!=(9,) or (self.scale<=0).any() or len(self.parameters)!=6 or any(w.shape!=shape for w,shape in zip(self.parameters,shapes)):
            raise ValueError('CNN参数尺寸不匹配')
        if not all(np.isfinite(w).all() for w in [self.mean,self.scale]+self.parameters):raise ValueError('CNN参数含非有限值')


def pack_cnn(payload):
    model=PortableCNN(payload)
    packed=np.concatenate([np.array([9,4,8,len(model.classes_)],dtype=float),model.mean,model.scale]+[w.ravel() for w in model.parameters])
    if len(packed)>2048:raise ValueError('CNN参数超过PL共用参数RAM容量')
    return packed
