"""训练报告的统一图表样式；只读取已有统计和帧，不修改模型参数。"""
from pathlib import Path

import numpy as np

BACKGROUND = '#10171c'
SURFACE = '#151f26'
TEXT = '#deeaed'
MUTED = '#91a7b0'
ACCENT = '#c6ed87'
CYAN = '#58d3cb'
PALETTE = [CYAN, ACCENT, '#e7bb70', '#bba1f3', '#ed9696', '#86baf4']
FEATURE_LABELS = ['回波/参考面积比（±150 bin）', '回波/参考面积比（±350 bin）',
                  '回波/参考峰高比', '回波核心面积占比', '回波尾部/前沿比',
                  '回波半高宽 / bin', '回波加权宽度 / bin', '回波峰高/面积比', '回波峰位时移 / bin']
ALGORITHM_NAMES = {'RandomForestClassifier':'随机森林', 'DecisionTreeClassifier':'决策树',
                   'MLPClassifier':'小型 MLP', 'TinyCNNClassifier':'小型 CNN'}


def _title(fig, title, subtitle=''):
    """按英寸而非整图百分比留白，13类长图也不会压到第一行子标题。"""
    height = fig.get_figheight()
    heading=fig.suptitle(title, x=.055, y=1-.18/height, ha='left', va='top', fontsize=16, color=TEXT)
    heading.set_in_layout(False)
    if subtitle:
        note=fig.text(.055, 1-.51/height, subtitle, ha='left', va='top', fontsize=10, color=MUTED)
        note.set_in_layout(False)
    fig.tight_layout(rect=[.015,.005,.99,1-.94/height], h_pad=2.2, w_pad=2.6)


def _save(fig, path, plt):
    fig.savefig(str(path), dpi=145, facecolor=BACKGROUND, bbox_inches='tight',
                bbox_extra_artists=fig.texts, pad_inches=.15)
    plt.close(fig)


def save_figures(model_path, report, X, labels, details, read_frame, smooth_histogram,
                 read_raw_frame, prefer_raw=False):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    from matplotlib.colors import LinearSegmentedColormap

    font_path = Path(__file__).with_name('report_assets')/'tdc_report_sans.otf'
    if not font_path.is_file():
        raise ValueError('缺少报告字体：{}'.format(font_path))
    family = font_manager.FontProperties(fname=str(font_path)).get_name()
    if hasattr(font_manager.fontManager,'addfont'):
        font_manager.fontManager.addfont(str(font_path))
    elif not any(entry.name==family for entry in font_manager.fontManager.ttflist):
        # PYNQ旧版Matplotlib没有addfont，直接注册本进程的字体条目即可。
        font_manager.fontManager.ttflist.append(font_manager.FontEntry(fname=str(font_path),name=family))
    theme = {'font.family':family, 'font.size':10, 'axes.unicode_minus':False,
             'figure.facecolor':BACKGROUND, 'axes.facecolor':SURFACE, 'axes.edgecolor':'#344650',
             'axes.labelcolor':MUTED, 'text.color':TEXT, 'xtick.color':MUTED, 'ytick.color':MUTED,
             'axes.titlepad':13, 'axes.titlesize':11, 'axes.spines.top':False,
             'axes.spines.right':False, 'grid.color':'#344650', 'grid.alpha':.5,
             'legend.facecolor':SURFACE, 'legend.edgecolor':'#344650', 'legend.fontsize':9}
    classes = list(report['holdout_confusion_labels'])
    confusion = np.asarray(report['holdout_confusion_matrix'])
    algorithm = ALGORITHM_NAMES.get(report['model_type'],report['model_type'])
    diagnostic = 'diagnostic only' in report.get('holdout_method','')
    validation = '同实物帧内留出，仅作诊断；新实物识别能力尚未验证。' if diagnostic else '按报告所列留出方式验证；准确率对应该验证集。'
    colors = [PALETTE[i%len(PALETTE)] for i in range(len(classes))]
    figures = []
    with matplotlib.rc_context(theme):
        print('正在生成统一风格的训练概览…',flush=True)
        fig,axes = plt.subplots(2,2,figsize=(14,max(9.7,8+len(classes)*.1)))
        counts = [int(np.sum(labels==name)) for name in classes]
        axes[0,0].bar(range(len(classes)),counts,color=colors,width=.65)
        axes[0,0].set_xticks(range(len(classes)))
        axes[0,0].set_xticklabels(classes,rotation=40,ha='right',fontsize=9)
        axes[0,0].set_title('各材质训练帧数',loc='left');axes[0,0].set_ylabel('帧数')
        axes[0,0].set_ylim(0,max(1,max(counts))*1.2)
        for i,count in enumerate(counts):axes[0,0].text(i,count+max(counts)*.02,str(count),ha='center',fontsize=9)
        cmap = LinearSegmentedColormap.from_list('tdc_matrix',[SURFACE,'#316963',ACCENT])
        ax = axes[0,1];ax.imshow(confusion,cmap=cmap,vmin=0)
        ax.set_xticks(range(len(classes)));ax.set_yticks(range(len(classes)))
        ax.set_xticklabels(classes,rotation=40,ha='right',fontsize=8 if len(classes)>16 else 9)
        ax.set_yticklabels(classes,fontsize=8 if len(classes)>16 else 9)
        ax.set_xlabel('预测材质');ax.set_ylabel('真实材质')
        ax.set_title('验证混淆矩阵 · 准确率 {:.1%}'.format(report['holdout_accuracy']),loc='left')
        for i in range(len(classes)):
            for j in range(len(classes)):
                if len(classes)<=20 or confusion[i,j]:
                    ax.text(j,i,str(confusion[i,j]),ha='center',va='center',fontsize=8,
                            color=BACKGROUND if confusion[i,j]>confusion.max()/2 else MUTED)
        for ax,index,title in [(axes[1,0],0,'回波/参考面积比分布（±150 bin）'),(axes[1,1],5,'回波半高宽分布 / bin')]:
            boxes=ax.boxplot([X[labels==name,index] for name in classes],labels=classes,patch_artist=True,
                             medianprops={'color':ACCENT,'linewidth':1.4},
                             whiskerprops={'color':MUTED},capprops={'color':MUTED},
                             flierprops={'marker':'.','markersize':3,'markeredgecolor':CYAN})
            for box,color in zip(boxes['boxes'],colors):box.set(facecolor=color,alpha=.24,edgecolor=color)
            ax.tick_params(axis='x',labelrotation=40,labelsize=9);ax.set_title(title,loc='left');ax.grid(axis='y')
        _title(fig,'{} · 训练评估（{}类）'.format(algorithm,len(classes)),validation)
        path=model_path.with_suffix('.overview.png');_save(fig,path,plt);figures.append(path)

        print('正在生成峰位核验图与逐类详情…',flush=True)
        examples=[]
        for name in classes:
            path,metadata,detail=next(item for item in details if item[1]['material_id']==name)
            raw=path.parents[1]/metadata.get('raw_path','')
            if prefer_raw and raw.is_file():
                raw.resolve().relative_to(path.parents[1].resolve())
                _,signal=read_raw_frame(raw,int(metadata['bin_num']))
            else:_,signal=read_frame(path)
            smooth,_=smooth_histogram(signal);examples.append((name,detail,signal,smooth))

        def draw_pair(axes,example):
            name,detail,signal,smooth=example
            for column,center,radius,title,color in [(0,detail['reference_bin'],350,'参考峰',MUTED),(1,detail['return_bin'],600,'真实回波',ACCENT)]:
                ax=axes[column];positions=np.arange(max(0,center-radius),min(len(signal),center+radius+1))
                ax.plot(positions,signal[positions],color='#6c8793',lw=.8,label='原始计数')
                ax.plot(positions,smooth[positions],color=color,lw=1.6,label='41 bin平滑')
                ax.axvline(center,color=color,ls='--',lw=1,alpha=.8)
                ax.set_title('{} · {} · bin {}'.format(name,title,center),loc='left',fontsize=11)
                ax.set_xlabel('bin 位置');ax.set_ylabel('计数');ax.grid(axis='y',alpha=.3)
                ax.legend(loc='upper right')

        fig,axes=plt.subplots(len(classes),2,figsize=(13.5,3.2*len(classes)+.8),squeeze=False)
        for row,example in enumerate(examples):draw_pair(axes[row],example)
        _title(fig,'各材质峰位核验','参考峰与真实回波分区展示；峰位沿用训练时的特征提取结果。')
        # 只绘制一次长图，再按真实Axes包围框裁出每类的小图。避免在ARM上
        # 重复创建/布局/绘制13个Figure；网页只解码选中材质的小图。
        from PIL import Image
        fig.canvas.draw();renderer=fig.canvas.get_renderer();tight=fig.get_tightbbox(renderer,bbox_extra_artists=fig.texts)
        row_bounds=[]
        for row in axes:
            boxes=[ax.get_tightbbox(renderer) for ax in row]
            row_bounds.append((min(box.x0 for box in boxes),min(box.y0 for box in boxes),
                               max(box.x1 for box in boxes),max(box.y1 for box in boxes)))
        base_dpi=fig.dpi;path=model_path.with_suffix('.peaks.png')
        _save(fig,path,plt);figures.append(path)
        with Image.open(str(path)) as source:
            for i,(x0,y0,x1,y1) in enumerate(row_bounds):
                top=int((tight.y1+.15-y1/base_dpi)*145)-12
                bottom=int((tight.y1+.15-y0/base_dpi)*145)+12
                source.crop((0,max(0,top),source.width,min(source.height,bottom))).save(str(model_path.with_suffix('.peak_{:02d}.png'.format(i))))

        print('正在生成特征重要性图…',flush=True)
        fig,ax=plt.subplots(figsize=(12,6));positions=np.arange(len(report['feature_importances']))
        ax.barh(positions,report['feature_importances'],xerr=report.get('feature_importance_std',np.zeros(len(positions))),
                color=CYAN,height=.6,error_kw={'ecolor':MUTED,'capsize':3})
        ax.set_yticks(positions);ax.set_yticklabels(FEATURE_LABELS[:len(positions)],fontsize=10);ax.invert_yaxis();ax.grid(axis='x')
        permutation='permutation' in report.get('importance_method','').lower() or 'permutation' in report.get('importance_label','').lower()
        ax.set_xlabel('置换后验证准确率下降值' if permutation else '特征重要性（模型统计量）')
        note='重要性用于解释当前模型，不能单独证明材料之间存在稳定物理差异。'
        if report['model_type']=='TinyCNNClassifier':
            note+=' 仅统计9维辅助特征，未包含256点波形分支的贡献。'
        _title(fig,'{} · 特征重要性'.format(algorithm),note)
        path=model_path.with_suffix('.importance.png');_save(fig,path,plt);figures.append(path)
    return figures
