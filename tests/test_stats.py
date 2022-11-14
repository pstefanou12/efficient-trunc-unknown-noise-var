# stats tests 

import unittest
import numpy as np
import torch as ch
from torch import Tensor
from torch.distributions import Uniform, Gumbel
from torch.nn import CosineSimilarity
from torch.nn import MSELoss
import torch.linalg as LA
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.metrics import confusion_matrix
import random

from delphi import stats 
from delphi import oracle
from delphi.utils.helpers import Parameters, logistic
from delphi.utils.datasets import make_train_and_val

# CONSTANT
mse_loss =  MSELoss()
cos_sim = CosineSimilarity()
G = Gumbel(0, 1)
seed = random.randint(0, 100)


class TestStats(unittest.TestCase): 
    """
    Test suite for the stats module.
    """
    # left truncated linear regression
    def test_known_truncated_regression(self):
        D, K = 3, 1
        SAMPLES = 5000
        w_ = Uniform(-1, 1)
        M = Uniform(-10, 10)
        # generate ground truth
        noise_var = 2*ch.ones(1, 1)
        W = w_.sample([K, D])
        W0 = w_.sample([1, 1])

        print(f"gt weight: {W}")
        print(f"gt intercept: {W0}")
        print(f"gt noise var: {noise_var}")
        # generate data
        X = M.sample(ch.Size([SAMPLES, D])) if isinstance(M, Uniform) else M.sample(ch.Size([SAMPLES]))
        y = X@W.T + W0 
        noised = y + ch.sqrt(noise_var) * ch.randn(y.size(0), 1)
        # generate ground-truth data
        phi = oracle.Left_Regression(ch.zeros(1))
        # truncate
        indices = phi(noised).nonzero()[:,0]
        x_trunc, y_trunc = X[indices], noised[indices]
        alpha = x_trunc.size(0) / X.size(0)
        print(f'alpha: {alpha}')
        # normalize input features
        l_inf = LA.norm(x_trunc, dim=-1, ord=float('inf')).max()
        beta = l_inf * (D ** .5)
        x_trunc /= beta
        X /= beta 

        gt_norm = LinearRegression()
        gt_norm.fit(X, y)
        gt_ = ch.from_numpy(np.concatenate([gt_norm.coef_.flatten(), gt_norm.intercept_]))

        # calculate empirical noise variance for regression 
        ols_trunc = LinearRegression()
        ols_trunc.fit(x_trunc, y_trunc)
        emp_noise_var = ch.from_numpy(ols_trunc.predict(X) - noised.numpy()).var(0)
        emp_ = ch.from_numpy(np.concatenate([ols_trunc.coef_.flatten(), ols_trunc.intercept_]))
        emp_mse_loss = mse_loss(emp_, gt_)
        emp_var_l1 = float(ch.abs(emp_noise_var - noise_var))
        print(f'emp mse loss: {emp_mse_loss}')
        print(f'emp noise var l1: {emp_var_l1}')

        # scale y features
        y_trunc_scale = y_trunc / ch.sqrt(noise_var)
        phi_scale = oracle.Left_Regression(phi.left / ch.sqrt(noise_var))
        # train algorithm
        train_kwargs = Parameters({'phi': phi_scale, 
                                'alpha': alpha,
                                'epochs': 5,
                                'trials': 3, 
                                'batch_size': 10,
                                'noise_var': 1.0}) 
        trunc_reg = stats.TruncatedLinearRegression(train_kwargs)
        trunc_reg.fit(x_trunc, y_trunc_scale)
        w_ = ch.cat([(trunc_reg.coef_).flatten(), trunc_reg.intercept_]) * ch.sqrt(noise_var)
        known_mse_loss = mse_loss(gt_, w_.flatten())
        print(f'known mse loss: {known_mse_loss}')
        self.assertTrue(known_mse_loss <= 3e-1, f'known mse loss: {known_mse_loss}')


    def test_unknown_truncated_regression(self):
        D, K = 10, 1
        SAMPLES = 5000
        w_ = Uniform(-1, 1)
        M = Uniform(-10, 10)
        # generate ground truth
        noise_var = 10*ch.ones(1, 1)
        W = w_.sample([K, D])
        W0 = w_.sample([1, 1])

        print(f"gt weight: {W}")
        print(f"gt intercept: {W0}")
        print(f"gt noise var: {noise_var}")
        # generate data
        X = M.sample(ch.Size([SAMPLES, D])) if isinstance(M, Uniform) else M.sample(ch.Size([SAMPLES]))
        y = X@W.T + W0 
        noised = y + ch.sqrt(noise_var) * ch.randn(y.size(0), 1)
        # generate ground-truth data
        phi = oracle.Left_Regression(ch.zeros(1))
        # truncate
        indices = phi(noised).nonzero()[:,0]
        x_trunc, y_trunc = X[indices], noised[indices]
        alpha = x_trunc.size(0) / X.size(0)
        print(f'alpha: {alpha}')
        # normalize input features
        l_inf = LA.norm(x_trunc, dim=-1, ord=float('inf')).max()
        beta = l_inf * (D ** .5)
        x_trunc /= beta
        X /= beta 

        gt_norm = LinearRegression()
        gt_norm.fit(X, noised)
        gt_ = ch.from_numpy(np.concatenate([gt_norm.coef_.flatten(), gt_norm.intercept_]))

        # calculate empirical noise variance for regression 
        ols_trunc = LinearRegression()
        ols_trunc.fit(x_trunc, y_trunc)
        emp_noise_var = ch.from_numpy(ols_trunc.predict(X) - noised.numpy()).var(0)
        emp_ = ch.from_numpy(np.concatenate([ols_trunc.coef_.flatten(), ols_trunc.intercept_]))
        emp_mse_loss = mse_loss(emp_, gt_)
        emp_var_l1 = float(ch.abs(emp_noise_var - noise_var))
        print(f'emp mse loss: {emp_mse_loss}')
        print(f'emp noise var l1: {emp_var_l1}')

        # scale y features by empirical noise variance
        y_trunc_emp_scale = y_trunc / ch.sqrt(emp_noise_var)
        phi_emp_scale = oracle.Left_Regression(phi.left / ch.sqrt(emp_noise_var))
        # train algorithm
        train_kwargs = Parameters({'phi': phi_emp_scale, 
                                'alpha': alpha,
                                'epochs': 30, 
                                'momentum': .5,
                                'trials': 3,
                                'batch_size': 100,
                                'var_lr': 1e-2,})
        unknown_trunc_reg = stats.TruncatedLinearRegression(train_kwargs)
        unknown_trunc_reg.fit(x_trunc, y_trunc_emp_scale)
        w_ = ch.cat([(unknown_trunc_reg.coef_).flatten(), unknown_trunc_reg.intercept_]) * ch.sqrt(emp_noise_var)
        noise_var_ = unknown_trunc_reg.variance_ * emp_noise_var
        unknown_mse_loss = mse_loss(gt_, w_.flatten())
        print(f'unknown mse loss: {unknown_mse_loss}')
        unknown_var_l1 = float(ch.abs(noise_var - noise_var_))
        print(f'unknown var l1: {unknown_var_l1}')
        self.assertTrue(unknown_mse_loss <= emp_mse_loss, f'unknown mse loss: {unknown_mse_loss}')
        self.assertTrue(unknown_var_l1 <= emp_var_l1, f'unknown var l1: {unknown_var_l1}')

    # left truncated binary classification task
    def test_truncated_logistic_regression(self):
        d, k = 5, 1
        C = -1.0
        # ground-truth logistic regression model 
        gt = ch.nn.Linear(in_features=d, out_features=k, bias=True)
        W = Uniform(-1, 1)
        U = Uniform(-5, 5)
        gt.weight = ch.nn.Parameter(W.sample([k, d]))
        gt.bias = ch.nn.Parameter(W.sample([1, k]))
        gt_ = ch.cat([gt.weight.flatten(), gt.bias.flatten()])

        # input features
        X = U.sample([10000, d])
        # latent variables
        z = gt(X) + logistic.sample([X.size(0), 1])
        # classification
        y = (z > 0).float()

        # generate ground-truth data
        phi = oracle.Left_Regression(Tensor([C]))
        phi_gumbel = oracle.GumbelLogisticLeftTruncation(Tensor([C]))
        indices = phi(z).nonzero(as_tuple=True)
        x_trunc = X[indices[0]]
        y_trunc = y[indices][...,None]
        alpha = x_trunc.size(0) / X.size(0)
        print(f'C: {C}')
        print(f'alpha: {alpha}')
                
        sklearn = LogisticRegression(penalty='none', fit_intercept=True)
        sklearn.fit(X, y.flatten())
        sklearn_ = ch.from_numpy(np.concatenate([sklearn.coef_.flatten(), sklearn.intercept_]))
        print(f'sklearn: {sklearn_}')
        pred = sklearn.predict(X)
        acc = np.equal(pred, y.flatten()).sum() / len(y)
        print(f'sklearn acc: {acc}')
        sklearn_conf_matrix = confusion_matrix(y, pred)
        print(f'sklearn confusion matrix: \n {sklearn_conf_matrix}')
        
        trunc_sklearn = LogisticRegression(penalty='none', fit_intercept=True)
        trunc_sklearn.fit(x_trunc, y_trunc.flatten())
        trunc_sklearn_ = ch.from_numpy(np.concatenate([trunc_sklearn.coef_.flatten(), trunc_sklearn.intercept_]))
        print(f'trunc sklearn: {trunc_sklearn_}')
        trunc_sklearn_cos_sim = float(cos_sim(trunc_sklearn_[None,...], sklearn_[None,...]))
        pred = trunc_sklearn.predict(X)
        trunc_sklearn_acc = np.equal(pred, y.flatten()).sum() / len(y)
        print(f'trunc sklearn acc: {trunc_sklearn_acc}')
        print(f'trunc sklearn cos sim: {trunc_sklearn_cos_sim}')
        trunc_sklearn_conf_matrix = confusion_matrix(y, pred)
        print(f'trunc sklearn confusion matrix: \n {trunc_sklearn_conf_matrix}')
                        
        id_ = oracle.Identity()
        train_kwargs = Parameters({'phi': id_,
                            'alpha': alpha,
                            'fit_intercept': True, 
                            'momentum': 0.0,
                            'normalize': False, 
                            'batch_size': 100,
                            'epochs': 30,
                            'trials': 3,
                            'verbose': True,
                            'early_stopping': True, 
                            'num_samples': 100})
        ch.manual_seed(seed)
        trunc_log_reg = stats.TruncatedLogisticRegression(train_kwargs)
        trunc_log_reg.fit(x_trunc, y_trunc) 
        trunc_log_reg_ = ch.cat([trunc_log_reg.coef_.flatten(), trunc_log_reg.intercept_])
        print(f'id trunc log reg: {trunc_log_reg_}')
        trunc_log_reg_cos_sim = float(cos_sim(trunc_log_reg_[None,...], sklearn_[None,...]))
        trunc_log_reg_pred = trunc_log_reg.predict(X)
        trunc_log_reg_acc = trunc_log_reg_pred.eq(y).sum() / len(y)
        print(f'id trunc log reg accuracy: {trunc_log_reg_acc}')
        print(f'id trunc cos sim: {trunc_log_reg_cos_sim}')
        trunc_log_reg_conf_matrix = confusion_matrix(y, trunc_log_reg_pred)
        print(f'id trunc log reg confusion matrix: \n {trunc_log_reg_conf_matrix}')
        
        train_kwargs = Parameters({'phi': id_,
                            'alpha': alpha,
                            'fit_intercept': True, 
                            'normalize': False, 
                            'batch_size': 100,
                            'epochs': 30,
                            'momentum': 0.0,
                            'trials': 3,
                            'multi_class': 'multinomial', 
                            'verbose': True,
                            'early_stopping': True,
                            'num_samples': 100})
        ch.manual_seed(seed)
        trunc_multi_log_reg = stats.TruncatedLogisticRegression(train_kwargs)
        trunc_multi_log_reg.fit(x_trunc, y_trunc.flatten().long()) 
        trunc_multi_log_reg_diff = ch.cat([trunc_multi_log_reg.coef_[1] - trunc_multi_log_reg.coef_[0], 
        (trunc_multi_log_reg.intercept_[1] - trunc_multi_log_reg.intercept_[0])[...,None]])
        trunc_multi_log_reg_ = ch.cat([trunc_multi_log_reg.coef_, trunc_multi_log_reg.intercept_[...,None]], axis=1)
        trunc_multi_cos_sim = float(cos_sim(trunc_multi_log_reg_diff[None,...], sklearn_[None,...]))
        trunc_multi_log_reg_pred = trunc_multi_log_reg.predict(X)
        trunc_multi_log_reg_acc = trunc_multi_log_reg_pred.eq(y.flatten()).sum() / len(y)
        print(f'id trunc multi log reg accuracy: {trunc_multi_log_reg_acc}')
        print(f'id trunc multi cos sim: {trunc_multi_cos_sim}')
        trunc_multi_log_reg_conf_matrix = confusion_matrix(y, trunc_multi_log_reg_pred)
        print(f'id trunc multi log reg confusion matrix: \n {trunc_multi_log_reg_conf_matrix}')
        
        train_kwargs = Parameters({'phi': phi,
                            'alpha': alpha,
                            'fit_intercept': True, 
                            'momentum': 0.5,
                            'normalize': False, 
                            'batch_size': 100,
                            'epochs': 30,
                            'trials': 3,
                            'verbose': True,
                            'early_stopping': True, 
                            'num_samples': 100})
        ch.manual_seed(seed)
        size = trunc_log_reg_[None,...].size()
        print(f'trunc log reg size: {size}')
        trunc_log_reg = stats.TruncatedLogisticRegression(train_kwargs, weight=trunc_log_reg_[None,...])
        trunc_log_reg.fit(x_trunc, y_trunc) 
        trunc_log_reg_ = ch.cat([trunc_log_reg.coef_.flatten(), trunc_log_reg.intercept_])
        print(f'trunc log reg: {trunc_log_reg_}')
        trunc_log_reg_cos_sim = float(cos_sim(trunc_log_reg_[None,...], sklearn_[None,...]))
        trunc_log_reg_pred = trunc_log_reg.predict(X)
        trunc_log_reg_acc = trunc_log_reg_pred.eq(y).sum() / len(y)
        print(f'trunc log reg accuracy: {trunc_log_reg_acc}')
        print(f'trunc log reg cos sim: {trunc_log_reg_cos_sim}')
        self.assertTrue(trunc_log_reg_cos_sim >= .9, f'trunc log reg cos sim: {trunc_log_reg_cos_sim}')
        trunc_log_reg_conf_matrix = confusion_matrix(y, trunc_log_reg_pred)
        print(f'trunc log reg confusion matrix: \n {trunc_sklearn_conf_matrix}')
        
        train_kwargs = Parameters({'phi': phi_gumbel,
                            'alpha': alpha,
                            'fit_intercept': True, 
                            'normalize': False, 
                            'batch_size': 100,
                            'epochs': 30,
                            'momentum': 0.5,
                            'trials': 3,
                            'multi_class': 'multinomial', 
                            'verbose': True,
                            'early_stopping': True,
                            'num_samples': 100})
        ch.manual_seed(seed)
        trunc_multi_log_reg = stats.TruncatedLogisticRegression(train_kwargs, weight=trunc_multi_log_reg_.T)
        trunc_multi_log_reg.fit(x_trunc, y_trunc.flatten().long()) 
        trunc_multi_log_reg_diff = ch.cat([trunc_multi_log_reg.coef_[1] - trunc_multi_log_reg.coef_[0], 
        (trunc_multi_log_reg.intercept_[1] - trunc_multi_log_reg.intercept_[0])[...,None]])
        trunc_multi_log_reg_ = ch.cat([trunc_multi_log_reg.coef_, trunc_multi_log_reg.intercept_[...,None]], axis=1)
        trunc_multi_cos_sim = float(cos_sim(trunc_multi_log_reg_diff[None,...], sklearn_[None,...]))
        self.assertTrue(trunc_multi_cos_sim >= .9, f'trunc multi cos sim: {trunc_multi_cos_sim}')
        trunc_multi_log_reg_pred = trunc_multi_log_reg.predict(X)
        trunc_multi_log_reg_acc = trunc_multi_log_reg_pred.eq(y.flatten()).sum() / len(y)
        print(f'trunc multi log reg accuracy: {trunc_multi_log_reg_acc}')
        print(f'trunc multi cos sim: {trunc_multi_cos_sim}')
        trunc_multi_log_reg_conf_matrix = confusion_matrix(y, trunc_multi_log_reg_pred)
        print(f'trunc multi log reg confusion matrix: \n {trunc_multi_log_reg_conf_matrix}')

    # gumbel ce classification task
    def test_gumbel_ce(self):     
        d, k = 20, 10
        # ground-truth logistic regression model 
        gt = ch.nn.Linear(in_features=d, out_features=k, bias=True)
        W = Uniform(-1, 1)
        U = Uniform(-5, 5)
        gt.weight = ch.nn.Parameter(W.sample([k, d]))
        gt.bias = ch.nn.Parameter(W.sample([1, k]))

        # input features
        X = U.sample([10000, d])
        # latent variables
        stacked = gt(X).repeat(100, 1, 1)
        noised = stacked + G.sample(stacked.size())
        # classification
        y = noised.mean(0).argmax(-1).long()

        sklearn = LogisticRegression(penalty='none', fit_intercept=True)
        sklearn.fit(X, y.flatten())
        sklearn_ = ch.from_numpy(np.concatenate([sklearn.coef_, sklearn.intercept_[...,None]], axis=1))
        print(f'sklearn: {sklearn_}')
        pred = sklearn.predict(X)
        acc = np.equal(pred, y.flatten()).sum() / len(y)
        print(f'sklearn acc: {acc}')
        sklearn_conf_matrix = confusion_matrix(y, pred)
        print(f'sklearn confusion matrix: \n {sklearn_conf_matrix}')

        train_kwargs = Parameters({
                            'batch_size': 100,
                            'momentum': 0.5,
                            'epochs': 30,
                            'trials': 3,
                            'verbose': True,
                            'early_stopping': True,
                            'workers': 0,
                            'num_samples': 100})        
        ch.manual_seed(seed)
        X_ones = ch.cat([X, ch.ones(X.size(0), 1)], axis=1)
        gumbel_model = stats.GumbelCEModel(train_kwargs, X_ones.size(1), len(y.unique()))
        trainer = Trainer(gumbel_model, train_kwargs)
        train_loader, val_loader = make_train_and_val(train_kwargs, X_ones, y)
        trainer.train_model((train_loader, val_loader))
        gumbel_ = gumbel_model.model                
        gumbel_cos_sim = float(cos_sim(gumbel_.flatten()[None,...], sklearn_.flatten()[None,...]))
        gumbel_pred = gumbel_model.predict(X_ones)
        gumbel_acc = gumbel_pred.eq(y).sum() / len(y)
        print(f'gumbel accuracy: {gumbel_acc}')
        print(f'gumbel cos sim: {gumbel_cos_sim}')
        gumbel_conf_matrix = confusion_matrix(y[...,None], gumbel_pred)
        print(f'trunc gumbel confusion matrix: \n {gumbel_conf_matrix}')

    # softmax classification task
    def test_softmax(self): 
        d, k = 20, 10
        # ground-truth logistic regression model 
        gt = ch.nn.Linear(in_features=d, out_features=k, bias=True)
        W = Uniform(-1, 1)
        U = Uniform(-5, 5)
        gt.weight = ch.nn.Parameter(W.sample([k, d]))
        gt.bias = ch.nn.Parameter(W.sample([1, k]))

        # input features
        X = U.sample([10000, d])
        # latent variables
        stacked = gt(X).repeat(100, 1, 1)
        noised = stacked + G.sample(stacked.size())
        # classification
        y = noised.mean(0).argmax(-1).long()

        sklearn = LogisticRegression(penalty='none', fit_intercept=True)
        sklearn.fit(X, y)
        sklearn_ = ch.from_numpy(np.concatenate([sklearn.coef_, sklearn.intercept_[...,None]], axis=1))
        print(f'sklearn: {sklearn_}')
        pred = sklearn.predict(X)
        acc = np.equal(pred, y).sum() / len(y)
        print(f'sklearn acc: {acc}')
        sklearn_conf_matrix = confusion_matrix(y, pred)
        print(f'sklearn confusion matrix: \n {sklearn_conf_matrix}')

        train_kwargs = Parameters({
                            'batch_size': 100,
                            'epochs': 30,
                            'momentum': 0.5,
                            'trials': 3,
                            'verbose': True,
                            'early_stopping': True,
                            'workers': 0})        
        ch.manual_seed(seed)
        X_ones = ch.cat([X, ch.ones(X.size(0), 1)], axis=1)
        softmax_model = stats.SoftmaxModel(train_kwargs, X_ones.size(1), len(y.unique()))
        trainer = Trainer(softmax_model, train_kwargs) 
        train_loader, val_loader = make_train_and_val(train_kwargs, X_ones, y)
        trainer.train_model((train_loader, val_loader))
        softmax_ = softmax_model.model

        softmax_cos_sim = float(cos_sim(softmax_.flatten()[None,...], sklearn_.flatten()[None,...]))
        softmax_pred = softmax_model.predict(X_ones)
        softmax_acc = softmax_pred.eq(y).sum() / len(y)
        print(f'softmax accuracy: {softmax_acc}')
        print(f'softmax cos sim: {softmax_cos_sim}')
        softmax_conf_matrix = confusion_matrix(y, softmax_pred)
        print(f'softmax confusion matrix: \n {softmax_conf_matrix}')
        

if __name__ == '__main__':
    unittest.main()
