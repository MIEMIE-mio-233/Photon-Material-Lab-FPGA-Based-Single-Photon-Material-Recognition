"""按需绘制单张训练图。由独立子进程调用，不在网页服务内驻留模型。"""
import json
import uuid
from pathlib import Path
import numpy as np
from training_figures import BACKGROUND,SURFACE,TEXT,MUTED,ACCENT,CYAN,PALETTE,FEATURE_LABELS,ALGORITHM_NAMES,_title


def setup():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    font=Path(__file__).with_name('report_assets')/'tdc_report_sans.otf'
    if not font.is_file():raise ValueError('缺少报告字体')
    family=font_manager.FontProperties(fname=str(font)).get_name()
    if hasattr(font_manager.fontManager,'addfont'):font_manager.fontManager.addfont(str(font))
    elif not any(entry.name==family for entry in font_manager.fontManager.ttflist):
        font_manager.fontManager.ttflist.append(font_manager.FontEntry(fname=str(font),name=family))
    return matplotlib,plt,{'font.family':family,'font.size':10,'axes.unicode_minus':False,
        'figure.facecolor':BACKGROUND,'axes.facecolor':SURFACE,'axes.edgecolor':'#344650',
        'axes.labelcolor':MUTED,'text.color':TEXT,'xtick.color':MUTED,'ytick.color':MUTED,
        'axes.titlepad':13,'axes.titlesize':11,'axes.spines.top':False,'axes.spines.right':False,
        'grid.color':'#344650','grid.alpha':.5,'legend.facecolor':SURFACE,'legend.edgecolor':'#344650','legend.fontsize':9}


def overview(report,data,plt):
    from matplotlib.colors import LinearSegmentedColormap
    classes=report['class_names'];X=data['features'];labels=data['labels']
    confusion_classes=['未覆盖距离'if c=='__rejected__'else c for c in report.get('holdout_confusion_labels',classes)]
    fig,axes=plt.subplots(2,2,figsize=(13,max(9,8+len(classes)*.08)))
    counts=[int(np.sum(labels==name)) for name in classes]
    colors=[PALETTE[i%len(PALETTE)] for i in range(len(classes))]
    axes[0,0].bar(range(len(classes)),counts,color=colors,width=.65)
    axes[0,0].set_xticks(range(len(classes)));axes[0,0].set_xticklabels(classes,rotation=40,ha='right',fontsize=9)
    axes[0,0].set_title('各材质训练帧数',loc='left');axes[0,0].set_ylabel('帧数')
    for i,count in enumerate(counts):axes[0,0].text(i,count,str(count),ha='center',va='bottom',fontsize=8)
    matrix=np.asarray(report['holdout_confusion_matrix']);ax=axes[0,1]
    ax.imshow(matrix,cmap=LinearSegmentedColormap.from_list('tdc_matrix',[SURFACE,'#316963',ACCENT]),vmin=0)
    ax.set_xticks(range(len(confusion_classes)));ax.set_yticks(range(len(confusion_classes)))
    ax.set_xticklabels(confusion_classes,rotation=40,ha='right',fontsize=8);ax.set_yticklabels(confusion_classes,fontsize=8)
    ax.set_xlabel('预测材质');ax.set_ylabel('真实材质')
    ax.set_title('验证混淆矩阵 · 准确率 {:.1%}'.format(report['holdout_accuracy']),loc='left')
    for i,j in np.ndindex(matrix.shape):
        if len(classes)<=20 or matrix[i,j]:
            ax.text(j,i,str(matrix[i,j]),ha='center',va='center',fontsize=8,
                    color=BACKGROUND if matrix[i,j]>matrix.max()/2 else MUTED)
    for ax,index,title in [(axes[1,0],0,'面积比 ±150 分布'),(axes[1,1],5,'回波半高宽分布 / bin')]:
        boxes=ax.boxplot([X[labels==name,index] for name in classes],labels=classes,patch_artist=True,
            medianprops={'color':ACCENT},whiskerprops={'color':MUTED},capprops={'color':MUTED},
            flierprops={'marker':'.','markersize':3,'markeredgecolor':CYAN})
        for box,color in zip(boxes['boxes'],colors):box.set(facecolor=color,alpha=.24,edgecolor=color)
        ax.tick_params(axis='x',labelrotation=40,labelsize=8);ax.set_title(title,loc='left');ax.grid(axis='y')
    return fig


def peaks(meta,data,index,plt):
    if not 0<=index<len(meta['examples']):raise ValueError('峰位核验类别超出范围')
    example=meta['examples'][index];fig,axes=plt.subplots(1,2,figsize=(12.5,4.6))
    for ax,part,label,color in zip(axes,['reference','return'],['参考峰','真实回波'],[MUTED,ACCENT]):
        key='{}_{}'.format(part,index);center=example['reference_bin' if part=='reference' else 'return_bin']
        ax.plot(data[key+'_x'],data[key+'_raw'],color='#6c8793',lw=.8,label='原始计数')
        ax.plot(data[key+'_x'],data[key+'_smooth'],color=color,lw=1.5,label='41 bin平滑')
        ax.axvline(center,color=color,ls='--',lw=1)
        ax.set_title('{} · {} · bin {}'.format(example['material'],label,center),loc='left')
        ax.set_xlabel('bin 位置');ax.set_ylabel('计数');ax.grid(axis='y');ax.legend()
    return fig


def importance(report,plt):
    fig,ax=plt.subplots(figsize=(12,6));positions=np.arange(len(report['feature_importances']))
    ax.barh(positions,report['feature_importances'],xerr=report.get('feature_importance_std',np.zeros(len(positions))),
        color=CYAN,height=.6,error_kw={'ecolor':MUTED,'capsize':3})
    ax.set_yticks(positions);ax.set_yticklabels(FEATURE_LABELS[:len(positions)]);ax.invert_yaxis();ax.grid(axis='x')
    ax.set_xlabel('置换后验证准确率下降值' if 'permutation' in report.get('importance_label','').lower() else '特征重要性（模型统计量）')
    return fig


def decision_tree(model,plt):
    tree=model.tree_;fig,ax=plt.subplots(figsize=(16,8));limit=3
    short=['面积比150','面积比350','峰高比','核心面积比','尾部/前沿比','半高宽','加权宽度','峰高/面积比','峰位时移']
    def visit(node,x,width,depth):
        leaf=tree.children_left[node]==-1;collapsed=not leaf and depth==limit
        values=np.asarray(tree.value[node]).reshape(-1);name=str(model.classes_[values.argmax()])
        text='叶节点' if leaf else short[tree.feature[node]]+' ≤ {:.3g}'.format(tree.threshold[node])
        text+='\n主类 {}\n样本 {}'.format(name,tree.n_node_samples[node])
        if collapsed:text+=' · 后续分支折叠'
        ax.text(x,-depth,text,ha='center',va='center',fontsize=8,
            bbox=dict(boxstyle='round,pad=.45',facecolor='#284437' if leaf else '#22323c',edgecolor=ACCENT if leaf else '#65818b'))
        if not leaf and not collapsed:
            for child,sign,label in [(tree.children_left[node],-1,'是'),(tree.children_right[node],1,'否')]:
                cx=x+sign*width/2;ax.plot([x,cx],[-depth-.17,-depth-.83],color='#65818b',lw=1)
                ax.text((x+cx)/2,-depth-.43,label,color=MUTED,fontsize=8,ha='center');visit(child,cx,width/2,depth+1)
    visit(0,0,8,0);ax.set_xlim(-8.7,8.7);ax.set_ylim(-3.7,.5);ax.axis('off')
    return fig


def dedicated(report,model,plt):
    kind=report['model_type'];d=report.get('model_diagnostics',{})
    if kind in ('RandomForestClassifier',):
        fig,axes=plt.subplots(1,2,figsize=(13,5.8));trees=model.estimators_;x=np.arange(1,len(trees)+1)
        if d.get('cumulative_accuracy'):
            axes[0].plot(x,100*np.asarray(d['tree_accuracy']),'.',color=MUTED,label='各单树')
            axes[0].plot(x,100*np.asarray(d['cumulative_accuracy']),color=ACCENT,label='前N棵树平均概率集成')
            axes[0].set_xlabel('树序号 / 累计树数');axes[0].set_ylabel('留出集准确率 / %');axes[0].legend();axes[0].grid()
            axes[0].set_title('既有留出模型的集成表现',loc='left')
        else:
            axes[0].bar(x,[tree.get_depth() for tree in trees],color=CYAN)
            axes[0].set_title('历史版本：各树深度（无逐树留出统计）',loc='left');axes[0].set_xlabel('树序号')
        axes[1].bar(x,[tree.get_n_leaves() for tree in trees],color=CYAN)
        axes[1].set_xlabel('树序号');axes[1].set_ylabel('叶节点数');axes[1].set_title('最终部署森林的结构规模',loc='left')
        return fig
    if kind=='DecisionTreeClassifier':return decision_tree(model,plt)
    if kind=='TinyCNNClassifier':
        fig,axes=plt.subplots(1,2,figsize=(13,6))
        losses=report.get('cnn_training_loss',[])
        axes[0].plot(np.arange(1,len(losses)+1),losses,color=ACCENT)
        axes[0].set(title='训练损失（不是独立测试效果）',xlabel='训练轮次',ylabel='交叉熵＋正则项');axes[0].grid()
        for j in range(4):axes[1].plot(np.arange(-2,3),model.parameters[0][:,j],marker='o',label='卷积核{}'.format(j+1))
        axes[1].set(title='4个参与训练的5点卷积核',xlabel='相对采样点',ylabel='权重');axes[1].legend();axes[1].grid()
        return fig
    classifier=model.named_steps['classifier'];classes=list(model.classes_)
    if kind=='MLPClassifier':
        fig,axes=plt.subplots(1,2,figsize=(13,6.3));sizes=[classifier.coefs_[0].shape[0]]+[w.shape[1] for w in classifier.coefs_]
        for i,size in enumerate(sizes):
            axes[0].text(i,.5,str(size),ha='center',va='center',fontsize=20,color=ACCENT,
                bbox=dict(boxstyle='round,pad=.6',facecolor=SURFACE,edgecolor='#65818b'))
            axes[0].text(i,.25,'输入层' if i==0 else '输出层' if i==len(sizes)-1 else '隐藏层 {}'.format(i),ha='center',fontsize=10)
            if i<len(sizes)-1:axes[0].annotate('',xy=(i+.75,.5),xytext=(i+.25,.5),arrowprops=dict(arrowstyle='->',color=MUTED))
        axes[0].set_xlim(-.6,len(sizes)-.4);axes[0].set_ylim(0,1);axes[0].axis('off')
        axes[0].set_title('网络结构 · {} / {}'.format(classifier.activation,classifier.solver),loc='left')
        axes[0].text(.5,.04,'迭代次数 {}；最终优化损失 {:.4g}\nLBFGS不提供逐轮损失曲线。'.format(classifier.n_iter_,classifier.loss_),ha='center',transform=axes[0].transAxes,color=MUTED,fontsize=9)
        weights=classifier.coefs_[-1].T;names=classes if len(weights)>1 else ['{} 相对 {}'.format(classes[1],classes[0])]
        vmax=max(float(np.abs(weights).max()),1e-12);image=axes[1].imshow(weights,aspect='auto',cmap='RdBu_r',vmin=-vmax,vmax=vmax)
        axes[1].set_yticks(range(len(names)));axes[1].set_yticklabels(names,fontsize=9)
        axes[1].set_xlabel('末层隐藏神经元序号（从0开始）');axes[1].set_title('输出层连接权重（非材质物理属性）',loc='left');fig.colorbar(image,ax=axes[1],shrink=.7)
        return fig
    raise ValueError('该模型暂不支持专属图')


def render_one(model_path,kind,output,class_index=0):
    """原子写入完整PNG；失败不会改动模型或先前已完成的图片。"""
    model_path,output=Path(model_path),Path(output)
    report=json.loads(model_path.with_suffix('.report.json').read_text(encoding='utf-8'))
    matplotlib,plt,theme=setup();data=None
    try:
        with matplotlib.rc_context(theme):
            if kind in ('overview','peaks'):
                snapshot=model_path.with_suffix('.plot_data.npz')
                if not snapshot.is_file():raise ValueError('旧版本缺少绘图快照；已缓存图仍可查看，新快照需重新训练生成')
                data=np.load(str(snapshot),allow_pickle=False)
            if kind=='overview':fig=overview(report,data,plt)
            elif kind=='peaks':
                meta=json.loads(model_path.with_suffix('.plot_meta.json').read_text(encoding='utf-8'))
                if meta['model_id']!=report['model_id']:raise ValueError('绘图快照版本不一致')
                fig=peaks(meta,data,class_index,plt)
            elif kind=='importance':fig=importance(report,plt)
            elif kind=='model':
                import joblib
                fig=dedicated(report,joblib.load(str(model_path))['model'],plt)
            else:raise ValueError('图表类型不正确')
            names={'overview':'数据与验证概览','peaks':'逐类峰位核验','importance':'特征重要性','model':'模型专属分析'}
            note='同实物帧内留出，仅作诊断；不代表新实物准确率。' if 'diagnostic only' in report.get('holdout_method','') else '验证范围沿用该模型报告；结构与权重不等于泛化准确率。'
            if kind=='importance' and report['model_type']=='TinyCNNClassifier':
                note+=' 仅统计9维辅助特征，未包含256点波形分支的贡献。'
            _title(fig,ALGORITHM_NAMES.get(report['model_type'],report['model_type'])+' · '+names[kind],note)
            temporary=output.with_name(output.stem+'.'+uuid.uuid4().hex+'.tmp.png')
            try:
                fig.savefig(str(temporary),dpi=120,facecolor=BACKGROUND,bbox_inches='tight',bbox_extra_artists=fig.texts,pad_inches=.15)
                temporary.replace(output)
            finally:
                if temporary.is_file():temporary.unlink()
    finally:
        if data is not None:data.close()
        plt.close('all')
