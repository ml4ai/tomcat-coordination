from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional, Union

import numpy as np
import pymc as pm

from coordination.common.types import TensorTypes
from coordination.module.latent_component.latent_component import \
    LatentComponent
from coordination.module.module import ModuleParameters, ModuleSamples
from coordination.module.parametrization2 import (HalfNormalParameterPrior,
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

        # If a parameter is shared across dimensions, we only have one parameter to infer.
        dim_mean_a0_dimensions = (
            1 if share_mean_a0_across_dimensions else dimension_size
        )
        dim_sd_a_dimensions = 1 if share_sd_a_across_dimensions else dimension_size

        # Check if the values passed as hyperparameter are in agreement with the dimension of the
        # variables that we need to infer. Parameters usually have dimensions: num subjects x
        # dimension size, but that changes depending on the sharing options.
        # TODO: replace asserts with ValueError
        if share_mean_a0_across_subjects:
            assert (dim_mean_a0_dimensions,) == mean_mean_a0.shape
            assert (dim_mean_a0_dimensions,) == sd_mean_a0.shape
        else:
            assert (num_subjects, dim_mean_a0_dimensions) == mean_mean_a0.shape
            assert (num_subjects, dim_mean_a0_dimensions) == sd_mean_a0.shape

        if share_sd_a_across_subjects:
            assert (dim_sd_a_dimensions,) == sd_sd_a.shape
        else:
            assert (num_subjects, dim_sd_a_dimensions) == sd_sd_a.shape

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

    def _check_parameter_dimensionality_consistency(self):
        """
        Check if their dimensionality is consistent with the sharing options.

        @raise ValueError: if either mean_a0 or sd_a have undefined values.
        """

        if self.parameters.mean_a0.value is None:
            raise ValueError(f"Value of {self.parameters.mean_a0.uuid} is undefined.")

        if self.parameters.sd_a.value is None:
            raise ValueError(f"Value of {self.parameters.sd_a.uuid} is undefined.")

        dim_mean_a0_dimensions = (
            1 if self.share_mean_a0_across_dimensions else self.dimension_size
        )
        if self.share_mean_a0_across_subjects:
            assert (dim_mean_a0_dimensions,) == self.parameters.mean_a0.value.shape
        else:
            assert (
                self.num_subjects,
                dim_mean_a0_dimensions,
            ) == self.parameters.mean_a0.value.shape

        dim_sd_a_dimensions = (
            1 if self.share_sd_a_across_dimensions else self.dimension_size
        )
        if self.share_sd_a_across_subjects:
            assert (dim_sd_a_dimensions,) == self.parameters.sd_a.value.shape
        else:
            assert (
                self.num_subjects,
                dim_sd_a_dimensions,
            ) == self.parameters.sd_a.value.shape

    @abstractmethod
    def create_random_variables(self):
        """
        Creates parameters and latent component variables in a PyMC model.
        """
        super().create_random_variables()

        with self.pymc_model:
            if self.mean_a0_random_variable is None:
                self._create_initial_mean_variable()

            if self.sd_a_random_variable is None:
                self._create_transition_standard_deviation_variable()

    def _create_initial_mean_variable(self):
        """
        Creates a latent variable for the mean of the initial state. We assume independence between
        the individual parameters per subject and dimension and sample them from a multivariate
        Gaussian.
        """

        dim_mean_a0_dimensions = (
            1 if self.share_mean_a0_across_dimensions else self.dimension_size
        )

        with self.pymc_model:
            if self.share_mean_a0_across_subjects:
                # When shared across subjects, only one parameter per dimension is needed.
                self.mean_a0_random_variable = pm.Normal(
                    name=self.parameters.mean_a0.uuid,
                    mu=self.parameters.mean_a0.prior.mean,
                    sigma=self.parameters.mean_a0.prior.sd,
                    size=dim_mean_a0_dimensions,
                    observed=self.parameters.mean_a0.value,
                )
            else:
                # Different parameters per subject and dimension.
                self.mean_a0_random_variable = pm.Normal(
                    name=self.parameters.mean_a0.uuid,
                    mu=self.parameters.mean_a0.prior.mean,
                    sigma=self.parameters.mean_a0.prior.sd,
                    size=(self.num_subjects, dim_mean_a0_dimensions),
                    observed=self.parameters.mean_a0.value,
                )

    def _create_transition_standard_deviation_variable(self):
        """
        Creates a latent variable for the standard deviation of the state transition (Gaussian
        random walk). We assume independence between the individual parameters per subject and
        dimension and sample them from a multivariate Half-Gaussian.
        """

        with self.pymc_model:
            dim_sd_a_dimensions = (
                1 if self.share_sd_a_across_dimensions else self.dimension_size
            )

            if self.share_sd_a_across_subjects:
                # When shared across subjects, only one parameter per dimension is needed.
                self.sd_a_random_variable = pm.HalfNormal(
                    name=self.parameters.sd_a.uuid,
                    sigma=self.parameters.sd_a.prior.sd,
                    size=dim_sd_a_dimensions,
                    observed=self.parameters.sd_a.value,
                )
            else:
                # Different parameters per subject and dimension.
                self.sd_a_random_variable = pm.HalfNormal(
                    name=self.parameters.sd_a.uuid,
                    sigma=self.parameters.sd_a.prior.sd,
                    size=(self.num_subjects, dim_sd_a_dimensions),
                    observed=self.parameters.sd_a.value,
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


class GaussianLatentComponentSamples(ModuleSamples):
    """
    This class stores samples generated by a Gaussian latent component.
    """

    def __init__(
        self,
        values: Union[List[np.ndarray], np.ndarray],
        time_steps_in_coordination_scale: Union[List[np.ndarray], np.ndarray],
    ):
        """
        Creates an object to store samples.

        @param values: sampled values of the latent component. For serial components, this will be
        a list of time series of values of different sizes. For non-serial components, this will be
        a tensor as the number of observations in time do not change for different sampled time
        series.
        @param time_steps_in_coordination_scale: indexes to the coordination used to generate the
        sample. If the component is in a different time scale from the time scale used to compute
        coordination, this mapping will tell which value of coordination to map to each sampled
        value of the latent component. For serial components, this will be a list of time series of
        indices of different sizes. For non-serial components, this will be a tensor as the number
        of observations in time do not change for different sampled time series.
        """
        super().__init__(values=values)

        self.time_steps_in_coordination_scale = time_steps_in_coordination_scale