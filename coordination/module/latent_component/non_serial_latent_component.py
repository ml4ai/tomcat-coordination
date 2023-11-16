from __future__ import annotations

from typing import List, Optional, Tuple, Union

import numpy as np
import pymc as pm
import pytensor.tensor as ptt
from scipy.stats import norm

from coordination.common.types import TensorTypes
from coordination.module.latent_component.latent_component import (LatentComponent,
                                                                   LatentComponentSamples)
from coordination.module.module import ModuleSamples
from coordination.module.constants import (DEFAULT_RELATIVE_FREQUENCY,
                                           DEFAULT_SUBJECT_REPETITION_FLAG,
                                           DEFAULT_FIXED_SUBJECT_SEQUENCE_FLAG,
                                           DEFAULT_NUM_SUBJECTS,
                                           DEFAULT_LATENT_DIMENSION_SIZE,
                                           DEFAULT_SELF_DEPENDENCY,
                                           DEFAULT_LATENT_MEAN_PARAM,
                                           DEFAULT_LATENT_SD_PARAM,
                                           DEFAULT_SHARING_ACROSS_SUBJECTS,
                                           DEFAULT_SHARING_ACROSS_DIMENSIONS)


class NonSerialLatentComponent(LatentComponent):
    """
    This class represents a latent component where there are observations for all the subjects at
    each time in the component's scale. A subject is then influenced by all the others.
    """

    def __init__(self,
                 uuid: str,
                 pymc_model: pm.Model,
                 num_subjects: int = DEFAULT_NUM_SUBJECTS,
                 dimension_size: int = DEFAULT_LATENT_DIMENSION_SIZE,
                 self_dependent: bool = DEFAULT_SELF_DEPENDENCY,
                 mean_mean_a0: np.ndarray = DEFAULT_LATENT_MEAN_PARAM,
                 sd_mean_a0: np.ndarray = DEFAULT_LATENT_SD_PARAM,
                 sd_sd_a: np.ndarray = DEFAULT_LATENT_SD_PARAM,
                 share_mean_a0_across_subjects: bool = DEFAULT_SHARING_ACROSS_SUBJECTS,
                 share_mean_a0_across_dimensions: bool = DEFAULT_SHARING_ACROSS_DIMENSIONS,
                 share_sd_a_across_subjects: bool = DEFAULT_SHARING_ACROSS_SUBJECTS,
                 share_sd_a_across_dimensions: bool = DEFAULT_SHARING_ACROSS_DIMENSIONS,
                 dimension_names: Optional[List[str]] = None,
                 coordination_samples: Optional[ModuleSamples] = None,
                 coordination_random_variable: Optional[pm.Distribution] = None,
                 latent_component_random_variable: Optional[pm.Distribution] = None,
                 mean_a0_random_variable: Optional[pm.Distribution] = None,
                 sd_a_random_variable: Optional[pm.Distribution] = None,
                 relative_frequency: float = DEFAULT_RELATIVE_FREQUENCY,
                 time_steps_in_coordination_scale: Optional[np.array] = None,
                 observed_values: Optional[TensorTypes] = None):
        """
        Creates a serial latent component.

        @param uuid: String uniquely identifying the latent component in the model.
        @param pymc_model: a PyMC model instance where modules are to be created at.
        @param num_subjects: the number of subjects that possess the component.
        @param dimension_size: the number of dimensions in the latent component.
        @param self_dependent: whether the latent variables in the component are tied to the past
            values from the same subject. If False, coordination will blend the previous latent
            value of a different subject with the value of the component at time t = 0 for the
            current subject (the latent component's prior for that subject).
        @param mean_mean_a0: mean of the hyper-prior of mu_a0 (mean of the initial value of the
            latent component).
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
            update_pymc_model. This variable must be set before such a call.
        @param latent_component_random_variable: latent component random variable to be used in a
            call to update_pymc_model. If not set, it will be created in such a call.
        @param mean_a0_random_variable: random variable to be used in a call to
            update_pymc_model. If not set, it will be created in such a call.
        @param sd_a_random_variable: random variable to be used in a call to
            update_pymc_model. If not set, it will be created in such a call.
        @param relative_frequency: a number larger or equal than 1 indicating the frequency in
            of the latent component with respect to coordination for sample data generation. For
            instance, if frequency is 2, there will be one component sample every other time step
            in the coordination scale.
        @param time_steps_in_coordination_scale: time indexes in the coordination scale for
            each index in the latent component scale.
        @param observed_values: observations for the serial latent component random variable. If
            a value is set, the variable is not latent anymore.
        """
        super().__init__(uuid=uuid,
                         pymc_model=pymc_model,
                         num_subjects=num_subjects,
                         dimension_size=dimension_size,
                         self_dependent=self_dependent,
                         mean_mean_a0=mean_mean_a0,
                         sd_mean_a0=sd_mean_a0,
                         sd_sd_a=sd_sd_a,
                         share_mean_a0_across_subjects=share_mean_a0_across_subjects,
                         share_mean_a0_across_dimensions=share_mean_a0_across_dimensions,
                         share_sd_a_across_subjects=share_sd_a_across_subjects,
                         share_sd_a_across_dimensions=share_sd_a_across_dimensions,
                         dimension_names=dimension_names,
                         coordination_samples=coordination_samples,
                         coordination_random_variable=coordination_random_variable,
                         latent_component_random_variable=latent_component_random_variable,
                         mean_a0_random_variable=mean_a0_random_variable,
                         sd_a_random_variable=sd_a_random_variable,
                         time_steps_in_coordination_scale=time_steps_in_coordination_scale,
                         observed_values=observed_values)

        self.relative_frequency = relative_frequency

    def draw_samples(self, seed: Optional[int], num_series: int) -> LatentComponentSamples:
        """
        Draws latent component samples using ancestral sampling and pairwise blending with
        coordination and different subjects.

        @param seed: random seed for reproducibility.
        @param num_series: how many series of samples to generate.
        @return: latent component samples for each coordination series.
        """
        super().draw_samples(seed, num_series)

        if self.relative_frequency >= 1:
            raise ValueError(f"The relative frequency ({self.relative_frequency}) must be a float "
                             f"number larger or equal than 1.")

        self._check_parameter_dimensionality_consistency()

        # Adjust dimensions according to parameter sharing specification
        if self.share_mean_a0_across_subjects:
            mean_a0 = self.parameters.mean_a0.value[None, None, :]
        else:
            mean_a0 = self.parameters.mean_a0.value[None, :]

        if self.share_sd_a_across_subjects:
            sd_a = self.parameters.sd_a.value[None, None, :]
        else:
            sd_a = self.parameters.sd_a.value[None, :]

        num_time_steps_in_cpn_scale = int(
            self.coordination_samples.num_time_steps / relative_frequency)

        time_steps_in_coordination_scale = (
                np.arange(num_time_steps_in_cpn_scale) * relative_frequency).astype(int)

        # Draw values from the system dynamics. The default model generates samples by following a Gaussian random walk
        # with blended values from different subjects according to the coordination levels over time. Child classes
        # can implement their own dynamics, like spring-mass-damping systems for instance.
        sampled_values = self._draw_from_system_dynamics(
            sampled_coordination=self.coordination_samples,
            time_steps_in_coordination_scale=samples.time_steps_in_coordination_scale,
            mean_a0=mean_a0,
            sd_a=sd_a)

        return LatentComponentSamples(
            values=sampled_values,
            time_steps_in_coordination_scale=time_steps_in_coordination_scale)

    def _draw_from_system_dynamics(self,
                                   sampled_coordination: np.ndarray,
                                   time_steps_in_coordination_scale: np.ndarray,
                                   mean_a0: np.ndarray,
                                   sd_a: np.ndarray) -> np.ndarray:
        """
        Draws values from the system dynamics. The default non serial component generates samples
        by following a Gaussian random walk with mean defined by blended values from
        different subjects according to the coordination levels over time. Child classes can
        implement their own dynamics, like spring-mass-damping systems for instance.

        @param sampled_coordination: sampled values of coordination (all series included).
        @param time_steps_in_coordination_scale: an array of indices representing time steps in the
        coordination scale that match those of the component's scale.
        @param mean_a0: initial mean of the latent component.
        @param sd_a: standard deviation of the Gaussian transition distribution.

        @return: sampled values.
        """

        # Dimension legend:
        # n: number of series (first dimension of coordination)
        # s: number of subjects
        # d: dimension size

        num_series = sampled_coordination.shape[0]
        num_time_steps = len(time_steps_in_coordination_scale)
        values = np.zeros((num_series, self.num_subjects, self.dim_value, num_time_steps))

        N = self.num_subjects
        sum_matrix_others = (np.ones((N, N)) - np.eye(N)) / (N - 1)

        for t in range(num_time_steps):
            if t == 0:
                values[..., 0] = norm(loc=mean_a0, scale=sd_aa).rvs(
                    size=(num_series, self.num_subjects, self.dim_value))
            else:
                # n x 1 x 1
                c = sampled_coordination[:, time_steps_in_coordination_scale[t]][:, None, None]

                prev_others = np.dot(sum_matrix_others, values[..., t - 1])  # n x s x d

                if self.self_dependent:
                    prev_same = values[..., t - 1]  # n x s x d
                else:
                    prev_same = mean_a0  # n x s x d

                blended_mean = (prev_others - prev_same) * c + prev_same  # n x s x d

                values[..., t] = norm(loc=blended_mean, scale=sd_a).rvs()

        return values

    def create_random_variables(self):
        """
        Creates parameters and non-serial latent component variables in a PyMC model.
        """
        super().create_random_variables()

        # Adjust dimensions for proper indexing and broadcast in the log_prob function.
        # We don't create a time dimension for the parameters in this component since there will
        # be entries for all the subjects at every time step.
        if self.share_mean_a0_across_subjects:
            # subject x dimension
            mean_a0 = self.mean_a0_random_variable.mean_a0[None, :].repeat(self.num_subjects,
                                                                           axis=0)
        else:
            mean_a0 = self.mean_a0_random_variable

        if self.share_sd_a_across_subjects:
            # subject x dimension
            sd_a = self.share_sd_a_across_subjects[None, :].repeat(self.num_subjects, axis=0)
        else:
            sd_a = self.sd_a_random_variable

        if self.latent_component_random_variable is not None:
            return

        log_prob_params = (mean_a0,
                           sd_a,
                           self.coordination_random_variable[
                               self.time_steps_in_coordination_scale],
                           np.array(self.self_dependent),
                           *self._get_extra_logp_params())

        # Add coordinates to the model
        self.pymc_model.add_coord(name=self.dimension_axis_name,
                                  values=self.dimension_names)
        self.pymc_model.add_coord(name=self.time_axis_name,
                                  values=[f"{sub}#{time}" for sub, time in
                                          zip(self.subject_indices,
                                              self.time_steps_in_coordination_scale)])

        with self.pymc_model:
            self.latent_component_random_variable = pm.DensityDist(
                self.uuid,
                *log_prob_params,
                logp=self._get_log_prob_fn(),
                random=self._get_random_fn(),
                dims=[self.subject_axis_name, self.dimension_axis_name, self.time_axis_name],
                observed=self.observed_values
            )

    def _get_extra_logp_params(self):
        """
        Gets extra parameters to be passed to the log_prob and random functions.
        """
        return ()

    def _get_logp_fn(self):
        """
        Gets a reference to a log_prob function.
        """
        return log_prob

    def _get_random_fn(self):
        """
        Gets a reference to a random function for prior predictive checks.
        """
        return random


###################################################################################################
# AUXILIARY FUNCTIONS
###################################################################################################

def log_prob(sample: ptt.TensorVariable,
             initial_mean: ptt.TensorVariable,
             sigma: ptt.TensorVariable,
             coordination: ptt.TensorVariable,
             self_dependent: ptt.TensorConstant):
    """
    Computes the log-probability function of a sample.

    @param sample: (subject x dimension x time) a single samples series.
    @param initial_mean: (subject x dimension) mean at t0 for each subject.
    @param sigma: (subject x dimension) a series of standard deviations. At each time the standard
        deviation is associated with the subject at that time.
    @param coordination: (time) a series of coordination values.
    @param self_dependent: a boolean indicating whether subjects depend on their previous values.
    @return: log-probability of the sample.
    """

    N = sample.shape[0]
    D = sample.shape[1]

    # log-probability at the initial time step
    total_logp = pm.logp(pm.Normal.dist(mu=initial_mean, sigma=sigma, shape=(N, D)),
                         sample[..., 0]).sum()

    # Contains the sum of previous values of other subjects for each subject scaled by 1/(s-1).
    # We discard the last value as that is not a previous value of any other.
    sum_matrix_others = (ptt.ones((N, N)) - ptt.eye(N)) / (N - 1)
    prev_others = ptt.tensordot(sum_matrix_others, sample, axes=(1, 0))[..., :-1]

    if self_dependent.eval():
        # The component's value for a subject depends on its previous value for the same subject.
        prev_same = sample[..., :-1]
    else:
        # The component's value for a subject does not depend on its previous value for the same subject.
        # At every time step, the value from others is blended with a fixed value given by the component's initial
        # mean.
        prev_same = initial_mean[:, :, None]

    # Coordination does not affect the component in the first time step because the subjects have no previous
    # dependencies at that time.
    c = coordination[None, None, 1:]  # 1 x 1 x t-1

    blended_mean = (prev_others - prev_same) * c + prev_same

    # Match the dimensions of the standard deviation with that of the blended mean
    sd = sigma[:, :, None]

    # Index samples starting from the second index (i = 1) so that we can effectively compare
    # current values against previous ones (prev_others and prev_same).
    total_logp += pm.logp(pm.Normal.dist(mu=blended_mean, sigma=sd, shape=blended_mean.shape),
                          sample[..., 1:]).sum()

    return total_logp


def random(initial_mean: np.ndarray,
           sigma: np.ndarray,
           coordination: np.ndarray,
           self_dependent: bool,
           rng: Optional[np.random.Generator] = None,
           size: Optional[Tuple[int]] = None) -> np.ndarray:
    """
    Generates samples from of a non-serial latent component for prior predictive checks.

    @param initial_mean: (subject x dimension) mean at t0 for each subject.
    @param sigma: (subject x dimension) a series of standard deviations. At each time the standard
        deviation is associated with the subject at that time.
    @param coordination: (time) a series of coordination values.
    @param self_dependent: a boolean indicating whether subjects depend on their previous values.
    @param rng: random number generator.
    @param size: size of the sample.

    @return: a serial latent component sample.
    """

    # TODO: Unify this with the class sampling method.

    T = coordination.shape[-1]
    N = num_subjects

    noise = rng.normal(loc=0, scale=1, size=size) * sigma[:, :, None]

    sample = np.zeros_like(noise)

    # Sample from prior in the initial time step
    sample[..., 0] = rng.normal(loc=initial_mean, scale=sigma, size=(num_subjects, dim_value))

    sum_matrix_others = (ptt.ones((N, N)) - ptt.eye(N)) / (N - 1)
    for t in np.arange(1, T):
        prev_others = np.dot(sum_matrix_others, sample[..., t - 1])  # s x d

        if self_dependent:
            # Previous sample from the same subject
            prev_same = sample[..., t - 1]
        else:
            # No dependency on the same subject. Sample from prior.
            prev_same = initial_mean

        blended_mean = (prev_others - prev_same) * coordination[t] + prev_same

        sample[..., t] = rng.normal(loc=blended_mean, scale=sigma)

    return sample + noise