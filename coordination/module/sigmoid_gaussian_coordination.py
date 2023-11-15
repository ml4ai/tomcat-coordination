from __future__ import annotations
from typing import Any, Optional
from abc import ABC

import numpy as np
import pymc as pm
from scipy.stats import norm

from coordination.common.functions import sigmoid
from coordination.module.parametrization2 import Parameter, HalfNormalParameterPrior, \
    NormalParameterPrior
from coordination.common.utils import set_random_seed
from coordination.module.module import ModuleSamples, Module, ModuleParameters
from coordination.module.coordination2 import Coordination
from coordination.module.constants import (DEFAULT_UNB_COORDINATION_MEAN_PARAM,
                                           DEFAULT_UNB_COORDINATION_SD_PARAM,
                                           DEFAULT_NUM_TIME_STEPS)


class SigmoidGaussianCoordination(Coordination):
    """
    This class models a time series of continuous unbounded coordination (C) and its bounded
    version tilde{C} = sigmoid(C).
    """

    def __init__(self,
                 pymc_model: pm.Model,
                 num_time_steps: int = DEFAULT_NUM_TIME_STEPS,
                 mean_mean_uc0: float = DEFAULT_UNB_COORDINATION_MEAN_PARAM,
                 sd_mean_uc0: float = DEFAULT_UNB_COORDINATION_SD_PARAM,
                 sd_sd_uc: float = DEFAULT_UNB_COORDINATION_SD_PARAM,
                 coordination_random_variable: Optional[pm.Distribution] = None,
                 mean_uc0_random_variable: Optional[pm.Distribution] = None,
                 sd_uc_random_variable: Optional[pm.Distribution] = None,
                 unbounded_coordination_observed_values: Optional[TensorTypes] = None):
        """
        Creates a coordination module with an unbounded auxiliary variable.

        @param pymc_model: a PyMC model instance where modules are to be created at.
        @param num_time_steps: number of time steps in the coordination scale.
        @param mean_mean_uc0: mean of the hyper-prior of mu_uc0 (mean of the initial value of the
            unbounded coordination).
        @param sd_mean_uc0: std of the hyper-prior of mu_uc0.
        @param sd_sd_uc: std of the hyper-prior of sigma_uc (std of the Gaussian random walk of
            the unbounded coordination).
        @param coordination_random_variable: random variable to be used in a call to
            create_random_variables. If not set, it will be created in such a call.
        @param mean_uc0_random_variable: random variable to be used in a call to
            create_random_variables. If not set, it will be created in such a call.
        @param sd_uc_random_variable: random variable to be used in a call to
            create_random_variables. If not set, it will be created in such a call.
        @param unbounded_coordination_observed_values: observations for the unbounded coordination
            random variable. If a value is set, the variable is not latent anymore.
        """
        super().__init__(
            pymc_model=pymc_model,
            parameters=SigmoidGaussianCoordinationParameters(
                module_uuid=Coordination.UUID,
                mean_mean_uc0=mean_mean_uc0,
                sd_mean_uc0=sd_mean_uc0,
                sd_sd_uc=sd_sd_uc),
            num_time_steps=num_time_steps,
            coordination_random_variable=coordination_random_variable,
            observed_values=unbounded_coordination_observed_values
        )

        self.mean_uc0_random_variable = mean_uc0_random_variable
        self.sd_uc_random_variable = sd_uc_random_variable

    def draw_samples(self, seed: Optional[int], num_series: int) -> CoordinationSamples:
        """
        Draw coordination samples. A sample is a time series of coordination.

        @param seed: random seed for reproducibility.
        @param num_series: how many series of samples to generate.
        @raise ValueError: if either mean_uc0 or sd_uc is None.
        @return: coordination samples. One coordination series per row.
        """
        super().draw_samples(seed, num_series)

        if self.parameters.sd_uc.value is None:
            raise ValueError(f"Value of {self.parameters.mean_uc0.uuid} is undefined.")

        if self.parameters.sd_uc.value is None:
            raise ValueError(f"Value of {self.parameters.sd_uc.uuid} is undefined.")

        # Gaussian random walk via re-parametrization trick
        unbounded_coordination = norm(loc=0, scale=1).rvs(
            size=(num_series, self.num_time_steps)) * self.parameters.sd_uc.value
        unbounded_coordination[:, 0] += self.parameters.mean_uc0.value
        unbounded_coordination = unbounded_coordination.cumsum(axis=1)

        # tilde{C} is a bounded version of coordination in the range [0,1]
        coordination = sigmoid(unbounded_coordination)

        return SigmoidGaussianCoordinationSamples(unbounded_coordination=unbounded_coordination,
                                                  coordination=coordination)

    def create_random_variables(self):
        """
        Creates parameters and coordination variables in a PyMC model.
        """

        with self.pymc_model:
            if self.mean_uc0_random_variable is None:
                self.mean_uc0_random_variable = pm.Normal(
                    name=self.parameters.mean_uc0.uuid,
                    mu=self.parameters.mean_uc0.prior.mean,
                    sigma=self.parameters.mean_uc0.prior.sd,
                    size=1,
                    observed=self.parameters.mean_uc0.value
                )
            if self.sd_uc_random_variable is None:
                self.sd_uc_random_variable = pm.HalfNormal(
                    name=self.parameters.sd_uc.uuid,
                    sigma=self.parameters.sd_uc.prior.sd,
                    size=1,
                    observed=self.parameters.sd_uc.value
                )

            if self.coordination_random_variable is None:
                # Add coordinates to the model
                if self.time_axis_name not in self.pymc_model.coords:
                    self.pymc_model.add_coord(name=self.time_axis_name,
                                              values=np.arange(self.num_time_steps))

                # Create variables
                prior = pm.Normal.dist(mu=self.mean_uc0_random_variable,
                                       sigma=self.sd_uc_random_variable)
                unbounded_coordination = pm.GaussianRandomWalk(
                    name="unbounded_coordination",
                    init_dist=prior,
                    sigma=self.sd_uc_random_variable,
                    dims=[self.time_axis_name],
                    observed=self.observed_values
                )

                self.coordination_random_variable = pm.Deterministic(
                    name=self.uuid,
                    var=pm.math.sigmoid(
                        unbounded_coordination),
                    dims=[self.time_axis_name]
                )


###################################################################################################
# AUXILIARY CLASSES
###################################################################################################

class SigmoidGaussianCoordinationParameters(ModuleParameters):
    """
    This class stores values and hyper-priors of the parameters of the coordination module.
    """

    def __init__(self,
                 module_uuid: str,
                 mean_mean_uc0: float,
                 sd_mean_uc0: float,
                 sd_sd_uc: float):
        """
        Creates an object to store coordination parameter info.

        @param mean_mean_uc0: mean of the hyper-prior of the unbounded coordination mean at time
            t = 0.
        @param sd_mean_uc0: standard deviation of the hyper-prior of the unbounded coordination
            mean at time t = 0.
        @param sd_sd_uc: standard deviation of the hyper-prior of the standard deviation used in
            the Gaussian random walk when transitioning from one time to the next.
        """
        super().__init__()
        self.mean_uc0 = Parameter(uuid=f"{module_uuid}_mean_uc0",
                                  prior=NormalParameterPrior(
                                      mean=np.array([mean_mean_uc0]),
                                      sd=np.array([sd_mean_uc0]))
                                  )
        self.sd_uc = Parameter(uuid=f"{module_uuid}_sd_uc",
                               prior=HalfNormalParameterPrior(np.array([sd_sd_uc])))


class SigmoidGaussianCoordinationSamples(ModuleSamples):

    def __init__(self,
                 unbounded_coordination: np.ndarray,
                 coordination: np.ndarray):
        """
        Creates an object to store coordination samples.

        @param unbounded_coordination: sampled values of an unbounded coordination variable.
            Unbounded coordination range from -Inf to +Inf.
        @param coordination: sampled coordination values in the range [0,1], or exactly 0 or 1 for
            discrete coordination.
        """
        super().__init__(coordination)

        self.unbounded_coordination = unbounded_coordination
