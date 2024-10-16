from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional, Union

import numpy as np
import pymc as pm

from coordination.common.types import TensorTypes
from coordination.common.utils import adjust_dimensions
from coordination.module.latent_component.latent_component import \
    LatentComponent
from coordination.module.module import ModuleParameters, ModuleSamples
from coordination.module.parametrization import (HalfNormalParameterPrior,
                                                 NormalParameterPrior,
                                                 Parameter)


class GaussianLatentComponent(LatentComponent, ABC):
    """
    This class represents a latent system component that evolve as a Gaussian random walk with
    mean defined by some blending strategy that takes coordination and past latent values from
    other subjects into consideration.
    """

    def __init__(
        self,
        pymc_model: pm.Model,
        uuid: str,
        num_subjects: int,
        dimension_size: int,
        self_dependent: bool,
        mean_mean_a0: np.ndarray,
        sd_mean_a0: np.ndarray,
        sd_sd_a: np.ndarray,
        share_mean_a0_across_subjects: bool,
        share_mean_a0_across_dimensions: bool,
        share_sd_a_across_subjects: bool,
        share_sd_a_across_dimensions: bool,
        dimension_names: Optional[List[str]] = None,
        coordination_samples: Optional[ModuleSamples] = None,
        coordination_random_variable: Optional[pm.Distribution] = None,
        latent_component_random_variable: Optional[pm.Distribution] = None,
        mean_a0_random_variable: Optional[pm.Distribution] = None,
        sd_a_random_variable: Optional[pm.Distribution] = None,
        time_steps_in_coordination_scale: Optional[np.array] = None,
        observed_values: Optional[TensorTypes] = None,
        mean_a0: Optional[Union[float, np.ndarray]] = None,
        sd_a: Optional[Union[float, np.ndarray]] = None,
        asymmetric_coordination: bool = False,
    ):
        """
        Creates a latent component module.

        @param uuid: string uniquely identifying the latent component in the model.
        @param pymc_model: a PyMC model instance where modules are to be created at.
        @param num_subjects: the number of subjects that possess the component.
        @param dimension_size: the number of dimensions in the latent component.
        @param self_dependent: whether the latent variables in the component are tied to the
            past values from the same subject. If False, coordination will blend the previous
            latent value of a different subject with the value of the component at time t = 0 for
            the current subject (the latent component's prior for that subject).
        @param mean_mean_a0: mean of the hyper-prior of mu_a0 (mean of the initial value of the
            latent component).
        @param sd_mean_a0: std of the hyper-prior of mu_a0.
        @param sd_sd_a: std of the hyper-prior of sigma_a (std of the Gaussian random walk of
            the latent component).
        @param share_mean_a0_across_subjects: whether to use the same mu_a0 for all subjects.
        @param share_mean_a0_across_dimensions: whether to use the same mu_a0 for all dimensions.
        @param share_sd_a_across_subjects: whether to use the same sigma_a for all subjects.
        @param share_sd_a_across_dimensions: whether to use the same sigma_a for all dimensions.
        @param dimension_names: the names of each dimension of the latent component. If not
            informed, this will be filled with numbers 0,1,2 up to dimension_size - 1.
        @param coordination_samples: coordination samples to be used in a call to draw_samples.
            This variable must be set before such a call.
        @param coordination_random_variable: coordination random variable to be used in a call to
            create_random_variables. This variable must be set before such a call.
        @param latent_component_random_variable: latent component random variable to be used in a
            call to create_random_variables. If not set, it will be created in such a call.
        @param mean_a0_random_variable: random variable to be used in a call to
            create_random_variables. If not set, it will be created in such a call.
        @param sd_a_random_variable: random variable to be used in a call to
            create_random_variables. If not set, it will be created in such a call.
        @param time_steps_in_coordination_scale: time indexes in the coordination scale for
            each index in the latent component scale.
        @param observed_values: observations for the latent component random variable. If a value
            is set, the variable is not latent anymore.
        @param mean_a0: initial value of the latent component. It needs to be given for sampling
            but not for inference if it needs to be inferred. If not provided now, it can be set
            later via the module parameters variable.
        @param sd_a: standard deviation of the latent component Gaussian random walk. It needs to
            be given for sampling but not for inference if it needs to be inferred. If not
            provided now, it can be set later via the module parameters variable.
        @param asymmetric_coordination: whether coordination is asymmetric or not. If asymmetric,
            the value of a component for one subject depends on the negative of the combination of
            the others.
        """

        super().__init__(
            uuid=uuid,
            pymc_model=pymc_model,
            parameters=GaussianLatentComponentParameters(
                module_uuid=uuid,
                mean_mean_a0=mean_mean_a0,
                sd_mean_a0=sd_mean_a0,
                sd_sd_a=sd_sd_a,
            ),
            num_subjects=num_subjects,
            dimension_size=dimension_size,
            self_dependent=self_dependent,
            dimension_names=dimension_names,
            coordination_samples=coordination_samples,
            coordination_random_variable=coordination_random_variable,
            latent_component_random_variable=latent_component_random_variable,
            time_steps_in_coordination_scale=time_steps_in_coordination_scale,
            observed_values=observed_values,
        )
        self.parameters.mean_a0.value = mean_a0
        self.parameters.sd_a.value = sd_a

        self.num_subjects = num_subjects
        self.dimension_size = dimension_size
        self.self_dependent = self_dependent
        self.share_mean_a0_across_subjects = share_mean_a0_across_subjects
        self.share_mean_a0_across_dimensions = share_mean_a0_across_dimensions
        self.share_sd_a_across_subjects = share_sd_a_across_subjects
        self.share_sd_a_across_dimensions = share_sd_a_across_dimensions
        self.dimension_names = dimension_names
        self.coordination_samples = coordination_samples
        self.coordination_random_variable = coordination_random_variable
        self.latent_component_random_variable = latent_component_random_variable
        self.mean_a0_random_variable = mean_a0_random_variable
        self.sd_a_random_variable = sd_a_random_variable
        self.time_steps_in_coordination_scale = time_steps_in_coordination_scale
        self.asymmetric_coordination = asymmetric_coordination

    @property
    def dimension_coordinates(self) -> Union[List[str], np.ndarray]:
        """
        Gets a list of values representing the names of each dimension.

        @return: a list of dimension names.
        """
        return (
            np.arange(self.dimension_size)
            if self.dimension_names is None
            else self.dimension_names
        )

    @abstractmethod
    def draw_samples(self, seed: Optional[int], num_series: int) -> ModuleSamples:
        """
        Checks whether parameter values are defined before sampling.

        @param seed: random seed for reproducibility.
        @param num_series: number of series to sample.
        @return: samples from the latent component.
        """
        if self.parameters.mean_a0.value is None:
            raise ValueError(f"Value of {self.parameters.mean_a0.uuid} is undefined.")

        if self.parameters.sd_a.value is None:
            raise ValueError(f"Value of {self.parameters.sd_a.uuid} is undefined.")

    @abstractmethod
    def create_random_variables(self):
        """
        Creates parameters and latent component variables in a PyMC model.
        """
        super().create_random_variables()

        with self.pymc_model:
            # Below we create the random variables representing the value of the component at time
            # t = 0 (mean_a0) and standard deviation of the Gaussian random walk (sd_a).
            if self.mean_a0_random_variable is None:
                dim_subjects = (
                    1 if self.share_mean_a0_across_subjects else self.num_subjects
                )
                dim_dimensions = (
                    1 if self.share_mean_a0_across_dimensions else self.dimension_size
                )
                self.mean_a0_random_variable = pm.Normal(
                    name=self.parameters.mean_a0.uuid,
                    mu=adjust_dimensions(
                        self.parameters.mean_a0.prior.mean,
                        num_rows=dim_subjects,
                        num_cols=dim_dimensions,
                    ),
                    sigma=adjust_dimensions(
                        self.parameters.mean_a0.prior.sd,
                        num_rows=dim_subjects,
                        num_cols=dim_dimensions,
                    ),
                    size=(dim_subjects, dim_dimensions),
                    observed=adjust_dimensions(
                        self.parameters.mean_a0.value,
                        num_rows=dim_subjects,
                        num_cols=dim_dimensions,
                    ),
                )

            if self.sd_a_random_variable is None:
                dim_subjects = (
                    1 if self.share_sd_a_across_subjects else self.num_subjects
                )
                dim_dimensions = (
                    1 if self.share_sd_a_across_dimensions else self.dimension_size
                )
                self.sd_a_random_variable = pm.HalfNormal(
                    name=self.parameters.sd_a.uuid,
                    sigma=adjust_dimensions(
                        self.parameters.sd_a.prior.sd,
                        num_rows=dim_subjects,
                        num_cols=dim_dimensions,
                    ),
                    size=(dim_subjects, dim_dimensions),
                    observed=adjust_dimensions(
                        self.parameters.sd_a.value,
                        num_rows=dim_subjects,
                        num_cols=dim_dimensions,
                    ),
                )


###################################################################################################
# AUXILIARY CLASSES
###################################################################################################


class GaussianLatentComponentParameters(ModuleParameters):
    """
    This class stores values and hyper-priors of the parameters of a Gaussian latent component.
    """

    def __init__(
        self,
        module_uuid: str,
        mean_mean_a0: np.ndarray,
        sd_mean_a0: np.ndarray,
        sd_sd_a: np.ndarray,
    ):
        """
        Creates an object to store latent component parameter info.

        @param module_uuid: unique ID of the latent component module.
        @param mean_mean_a0: mean of the hyper-prior of the mean at time t = 0.
        @param sd_mean_a0: standard deviation of the hyper-prior of the mean at time t = 0.
        @param sd_sd_a: standard deviation of the hyper-prior of the standard deviation used in
            the Gaussian random walk when transitioning from one time to the next.
        """
        super().__init__()

        self.mean_a0 = Parameter(
            uuid=f"{module_uuid}_mean_a0",
            prior=NormalParameterPrior(mean_mean_a0, sd_mean_a0),
        )
        self.sd_a = Parameter(
            uuid=f"{module_uuid}_sd_a", prior=HalfNormalParameterPrior(sd_sd_a)
        )
