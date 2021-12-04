"""
Censored normal distribution with oracle access (ie. known truncation set)
"""

import torch as ch
from torch import Tensor
from torch.distributions.multivariate_normal import MultivariateNormal
from torch.utils.data import DataLoader
from cox.utils import Parameters
import config
import copy

from .. import delphi
from .distributions import distributions
from ..oracle import oracle
from ..trainer import Trainer
from ..utils.datasets import CensoredNormalDataset, make_train_and_val_distr
from ..grad import CensoredMultivariateNormalNLL
from ..utils import defaults
from ..utils.helpers import Bounds, check_and_fill_args

# CONSTANTS 
DEFAULTS = {
        'epochs': (int, 1),
        'num_trials': (int, 3),
        'clamp': (bool, True), 
        'val': (float, .2),
        'lr': (float, 1e-1), 
        'step_lr': (int, 100),
        'step_lr_gamma': (float, .9), 
        'custom_lr_multiplier': (str, None), 
        'momentum': (float, 0.0), 
        'weight_decay': (float, 0.0), 
        'l1': (float, 0.0), 
        'eps': (float, 1e-5),
        'r': (float, 1.0), 
        'rate': (float, 1.5), 
        'batch_size': (int, 10),
        'tol': (float, 1e-1),
        'workers': (int, 0),
        'num_samples': (int, 10),
}

class CensoredNormal(distributions):
    """
    Censored normal distribution class.
    """
    def __init__(self,
            phi: oracle,
            alpha: float,
            kwargs: dict=None):
        """
        Args:
            
        """
        super(CensoredNormal).__init__()
        # instance variables
        assert isinstance(phi, oracle), "phi is type: {}. expected type oracle.oracle".format(type(phi))
        assert isinstance(alpha, float), "alpha is type: {}. expected type float.".format(type(alpha))
        self.phi = phi

        # algorithm hyperparameters
        self.args = check_and_fill_args(Parameters({**{'alpha': Tensor([alpha])}, **kwargs}), DEFAULTS)

    def fit(self, S: Tensor):
        """
        """
       
        self.train_loader_, self.val_loader_ = make_train_and_val_distr(self.args, S)
        self.censored = CensoredNormalModel(self.args, self.train_loader_.dataset, self.phi)
        # run PGD to predict actual estimates
        self.trainer = Trainer(self.censored, self.args.epochs, self.args.num_trials, self.args.tol)

        # run PGD for parameter estimation 
        self.trainer.train_model((self.train_loader_, self.val_loader_))
        
    @property 
    def loc(self): 
        """
        Returns the mean of the normal disribution.
        """
        return self.censored.model.loc.clone()

    @property 
    def variance(self): 
        """
        Returns the variance for the normal distribution.
        """
        return self.censored.model.covariance_matrix.clone()


class CensoredNormalModel(delphi.delphi):
    '''
    Model for censored normal distributions to be passed into trainer.
    '''
    def __init__(self, args, train_ds, phi): 
        '''
        Args: 
            args (cox.utils.Parameters) : parameter object holding hyperparameters
        '''
        super().__init__(args)
        self.phi = phi 
        self.train_ds = train_ds
        self.emp_loc, self.emp_covariance_matrix = None, None
        # initialize empirical estimates
        self.calc_emp_model()

    def pretrain_hook(self):
        self.radius = self.args.r * (ch.log(1.0 / self.args.alpha) / self.args.alpha.pow(2))
        # parameterize projection set
        T = self.emp_covariance_matrix.clone().inverse()
        v = self.emp_loc.clone() @ T

        if self.args.clamp:
            self.loc_bounds, self.scale_bounds = Bounds(v - self.radius, v + self.radius), \
             Bounds(ch.square(self.args.alpha / 12.0), T + self.radius)
        else:
            pass

        # initialize empirical model 
        self.model = MultivariateNormal(v, T)
        self.model.loc.requires_grad, self.model.covariance_matrix.requires_grad = True, True
        self.params = [self.model.loc, self.model.covariance_matrix]

    def calc_emp_model(self): 
        # initialize projection set
        self.emp_covariance_matrix = self.train_ds.covariance_matrix
        self.emp_loc = self.train_ds.loc

    def __call__(self, batch):
        '''
        Training step for defined model.
        Args: 
            i (int) : gradient step or epoch number
            batch (Iterable) : iterable of inputs that 
        '''
        loss = CensoredMultivariateNormalNLL.apply(self.model.loc, self.model.covariance_matrix, *batch, self.phi, self.args.num_samples, self.args.eps)
        return loss, None, None

    def iteration_hook(self, i, loop_type, loss, prec1, prec5, batch):
        '''
        Iteration hook for defined model. Method is called after each 
        training update.
        Args:
            loop_type (str) : 'train' or 'val'; indicating type of loop
            loss (ch.Tensor) : loss for that iteration
            prec1 (float) : accuracy for top prediction
            prec5 (float) : accuracy for top-5 predictions
        '''
        if self.args.clamp:
            self.model.loc.data = ch.clamp(self.model.loc.data, float(self.loc_bounds.lower), float(self.loc_bounds.upper))
            self.model.covariance_matrix.data = ch.clamp(self.model.covariance_matrix.data, float(self.scale_bounds.lower), float(self.scale_bounds.upper))
        else:
            pass

        # self.model.covariance_matrix.data = ch.ones(1, 1)


    def post_training_hook(self): 
        self.args.r *= self.args.rate
        # reparamterize distribution
        self.model.covariance_matrix.requires_grad, self.model.loc.requires_grad = False, False
        self.model.covariance_matrix.data = self.model.covariance_matrix.inverse()
        self.model.loc.data = self.model.loc  @ self.model.covariance_matrix
