"""区分实物、距离和批次的留出验证；超参数只在外层训练折中选择。"""
import numpy as np
from sklearn.model_selection import StratifiedKFold


def split_data(data):
    from train_material import holdout_indices
    labels, groups = data.labels, data.groups
    if all(len(set(groups[labels==c]))>=2 for c in set(labels)):
        return holdout_indices(labels,groups,data.frame_numbers)
    rounds=sorted(set(row.get('experiment_round') for _,row,_ in data.details if row.get('experiment_round')))
    if len(rounds)>=2:
        mask=np.asarray([row.get('experiment_round')==rounds[-1] for _,row,_ in data.details])
        if set(labels[mask])==set(labels) and set(labels[~mask])==set(labels):
            return np.flatnonzero(~mask),np.flatnonzero(mask),'held-out entire experiment round '+rounds[-1]+'; same physical specimens'
    if not any(row.get('distance_cm') is not None for _,row,_ in data.details):
        return holdout_indices(labels,groups,data.frame_numbers)
    cells={}
    for index,(_,row,_)in enumerate(data.details):
        key=(row['material_id'],row['specimen_id'],row.get('distance_cm'),row.get('illumination'))
        cells.setdefault(key,[]).append(index)
    test=[];independent=True
    for key,indices in cells.items():
        if len(indices)<2:raise ValueError('每件实物每个距离至少需要2帧')
        batches=sorted(set(data.details[i][1]['_run_key']for i in indices))
        if len(batches)>=2:
            test.extend(i for i in indices if data.details[i][1]['_run_key']==batches[-1])
        else:
            independent=False
            ordered=sorted(indices,key=lambda i:int(data.frame_numbers[i]))
            test.extend(ordered[-max(1,int(np.ceil(len(indices)*.2))):])
    test=np.asarray(sorted(test),dtype=int);train=np.setdiff1d(np.arange(len(labels)),test)
    method='held-out acquisition batch per specimen/distance'if independent else 'per specimen/distance last 20% frames; same batch diagnostic only'
    return train,test,method


def tune_dense(algorithm,options,data,train):
    from train_material import make_classifier,fit_classifier
    # 内层按材质×距离分层；批次数充足时按整个批次划分，避免重复帧泄漏。
    from sklearn.model_selection import GroupKFold
    labels=data.labels[train]
    batches=np.asarray([data.details[i][1]['_run_key']for i in train])
    split=None
    if len(set(batches))>=3:
        candidate=list(GroupKFold(3).split(data.features[train],labels,batches))
        if all(set(labels[a])==set(labels)for a,b in candidate):split=candidate
    if split is None:
        strata=np.asarray([str(data.labels[i])+':'+str(data.details[i][1].get('distance_cm'))for i in train])
        counts=[np.sum(strata==key)for key in set(strata)]
        folds=min(3,min(counts))
        if folds<2:return options,dict(skipped='训练折内样本不足，未调参')
        split=list(StratifiedKFold(folds,shuffle=True,random_state=42).split(data.features[train],strata))
        scope='training-fold stratified repeated-frame diagnostic only'
    else:scope='training-fold grouped batch CV'
    key='alpha'
    candidates=[dict(alpha=a,hidden_layer_sizes=h)for h in [(8,4),(16,8),(32,16)]for a in [.01,.1,1.]]
    trials=[]
    for candidate_parameters in candidates:
        value=candidate_parameters[key];parameters=dict(options,**candidate_parameters);scores=[];notices=[]
        for a,b in split:
            model=make_classifier(algorithm,parameters)
            notices.extend(fit_classifier(model,data.features[train[a]],labels[a]))
            scores.append(float(np.mean(model.predict(data.features[train[b]])==labels[b])))
        trials.append(dict(parameter=key,value=value,parameters=candidate_parameters,mean_accuracy=float(np.mean(scores)),fold_scores=scores,warnings=sorted(set(notices))))
        print('训练折内调参 {}：{:.1%}'.format(candidate_parameters,trials[-1]['mean_accuracy']),flush=True)
    # 分数相同时偏向更强正则，避免只因一次噪声选复杂边界。
    best=max(trials,key=lambda x:(x['mean_accuracy'],-x['value']if key=='C'else -sum(x['parameters']['hidden_layer_sizes']),x['value']))
    return dict(options,**best['parameters']),dict(scope=scope,selected=best['parameters'],trials=trials,outer_test_used=False)
