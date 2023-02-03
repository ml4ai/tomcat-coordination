from typing import Any, Optional, Tuple

import numpy as np
import pymc as pm
import pytensor as pt
import pytensor.tensor as ptt
from scipy.stats import norm

from coordination.common.utils import set_random_seed


def mixture_logp_with_self_dependency(mixture_component: Any,
                                      initial_mean: Any,
                                      sigma: Any,
                                      coordination: Any,
                                      prev_time: Any,
                                      prev_time_mask: ptt.TensorConstant,
                                      subject_mask: ptt.TensorConstant,
                                      expander_aux_mask_matrix: ptt.TensorConstant,
                                      aggregation_aux_mask_matrix: ptt.TensorVariable):
    C = coordination[None, :]  # 1 x t
    P = mixture_component[..., prev_time]  # s x d x t
    PTM = prev_time_mask[None, None, :]  # 1 x t
    SM = subject_mask[None, :]  # 1 x t

    num_time_steps = coordination.shape[-1]

    # num_subjects, dim_value, num_time_steps = mixture_component.shape
    # num_subjects = num_subjects.eval()

    # Log probability due to the initial step, when there's no previous observation (PTM == 0).
    # total_logp = pm.logp(
    #     pm.Normal.dist(mu=initial_mean[:, :, None], sigma=sigma[:, :, None], shape=mixture_component.shape),
    #     mixture_component)
    total_logp = pm.logp(
        pm.Normal.dist(mu=initial_mean, sigma=sigma, shape=mixture_component.shape),
        mixture_component)

    # We preserve the logp only in the time step where PTM == 0.
    total_logp = (total_logp * (1 - PTM) * SM).sum()

    # Contains the previous values from other individuals
    D = ptt.tensordot(expander_aux_mask_matrix, P, axes=(1, 0))  # s * (s-1) x d x t
    P_extended = ptt.repeat(P, repeats=(mixture_component.shape[0] - 1), axis=0)
    point_extended = ptt.repeat(mixture_component, repeats=(mixture_component.shape[0] - 1), axis=0)

    mean = (D - P_extended) * C[None, :] + P_extended

    # pdf = pm.math.exp(
    #     pm.logp(pm.Normal.dist(mu=mean, sigma=ptt.repeat(sigma, repeats=2, axis=0)[:, :, None], shape=D.shape),
    #             point_extended))
    pdf = pm.math.exp(pm.logp(pm.Normal.dist(mu=mean, sigma=sigma, shape=D.shape), point_extended))

    total_logp += (pm.math.log(ptt.tensordot(aggregation_aux_mask_matrix, pdf, axes=(1, 0))) * PTM * SM).sum()

    # # Log probability due to the influence of distinct subjects according to the mixture weight
    # for s1 in ptt.arange(num_subjects).eval():
    #     w = 0
    #     likelihood_per_subject = 0
    #
    #     for s2 in ptt.arange(num_subjects).eval():
    #         # ptt.switch(ptt.eq(s1, s2), 0, mixture_weights[0, w]).eval()
    #         if ptt.eq(s1, s2).eval():
    #             # weight = 1
    #             continue
    #         else:
    #             weight = mixture_weights[0, w]
    #             w += 1
    #
    #         means = (P[s2] - P[s1]) * C + P[s1]
    #         logp_s1_from_s2 = pm.logp(
    #             pm.Normal.dist(mu=means, sigma=sigma, shape=(dim_value, num_time_steps)),
    #             mixture_component[s1])
    #
    #         likelihood_per_subject += weight * pm.math.exp(logp_s1_from_s2)
    #
    #     # Multiply by PTM to ignore entries already accounted for in the initial time step (no previous observation)
    #     # Multiply by SM to ignore entries in time step without observations
    #     likelihood_per_subject = pm.math.log(likelihood_per_subject) * PTM * SM
    #
    #     total_logp += likelihood_per_subject.sum()

    return total_logp


def mixture_logp_without_self_dependency(mixture_component: Any,
                                         initial_mean: Any,
                                         sigma: Any,
                                         mixture_weights: Any,
                                         coordination: Any,
                                         prev_time: Any,
                                         prev_time_mask: ptt.TensorConstant,
                                         subject_mask: ptt.TensorConstant,
                                         num_subjects: ptt.TensorConstant,
                                         dim_value: ptt.TensorConstant,
                                         expander_aux_mask_matrix: ptt.TensorConstant,
                                         aggregation_aux_mask_matrix: ptt.TensorVariable):
    C = coordination[None, :]  # 1 x t
    P = mixture_component[..., prev_time]  # s x d x t
    PTM = prev_time_mask[None, :]  # 1 x t
    SM = subject_mask[None, :]  # 1 x t

    num_time_steps = coordination.shape[-1]

    # Log probability due to the initial step, when there's no previous observation (PTM == 0).
    total_logp = (pm.logp(
        pm.Normal.dist(mu=(1 - PTM) * initial_mean, sigma=sigma, shape=mixture_component.shape),
        mixture_component) * PTM * SM).sum()

    # Contains the previous values of other individuals
    D = ptt.tensordot(expander_aux_mask_matrix, P, axes=(1, 0))  # s * (s-1) x d x t
    P_extended = ptt.repeat(P, repeats=(mixture_component.shape[0] - 1), axis=0)
    point_extended = ptt.repeat(mixture_component, repeats=(mixture_component.shape[0] - 1), axis=0)

    mean = (D - P_extended) * C[None, :] + P_extended

    pdf = pm.math.exp(pm.logp(pm.Normal.dist(mu=mean, sigma=sigma, shape=D.shape), point_extended))

    total_logp += pm.math.log(ptt.tensordot(aggregation_aux_mask_matrix, pdf, axes=(1, 0))).sum()

    # # Log probability due to the influence of distinct subjects according to the mixture weight
    # for s1 in ptt.arange(num_subjects).eval():
    #     w = 0
    #     likelihood_per_subject = 0
    #
    #     for s2 in ptt.arange(num_subjects).eval():
    #         if s1 == s2:
    #             continue
    #
    #         means = (P[s2] - initial_mean) * C + initial_mean
    #         logp_s1_from_s2 = pm.logp(
    #             pm.Normal.dist(mu=means, sigma=sigma, shape=(dim_value, num_time_steps)),
    #             mixture_component[s1])
    #
    #         likelihood_per_subject += mixture_weights[s1, w] * pm.math.exp(logp_s1_from_s2)
    #         w += 1
    #
    #     # Multiply by PTM to ignore entries already accounted for in the initial time step (no previous observation)
    #     # Multiply by SM to ignore entries in time step without observations
    #     likelihood_per_subject = pm.math.log(likelihood_per_subject) * PTM * SM
    #
    #     total_logp += likelihood_per_subject.sum()

    return total_logp


def mixture_random_with_self_dependency(initial_mean: np.ndarray,
                                        sigma: np.ndarray,
                                        mixture_weights: np.ndarray,
                                        coordination: np.ndarray,
                                        prev_time: np.ndarray,
                                        prev_time_mask: np.ndarray,
                                        subject_mask: np.ndarray,
                                        num_subjects: int,
                                        dim_value: int,
                                        rng: Optional[np.random.Generator] = None,
                                        size: Optional[Tuple[int]] = None) -> np.ndarray:
    num_time_steps = coordination.shape[-1]
    noise = rng.normal(loc=0, scale=1, size=size) * sigma

    # We sample the influencers in each time step using the mixture weights
    influencers = []
    for subject in range(num_subjects):
        probs = np.insert(mixture_weights[0], subject, 0)
        influencers.append(rng.choice(a=np.arange(num_subjects), p=probs, size=num_time_steps))
    influencers = np.array(influencers)

    sample = np.zeros_like(noise)
    prior_sample = rng.normal(loc=initial_mean, scale=sigma, size=(num_subjects, dim_value))
    for t in np.arange(1, num_time_steps):
        # Previous sample from a different individual
        D = sample[..., prev_time[t]][influencers[..., t]]
        # Previous sample from the same individual
        S = sample[..., prev_time[t]]
        mean = ((D - S) * coordination[t] + S)

        transition_sample = rng.normal(loc=mean, scale=sigma)

        sample[..., t] = (prior_sample * (1 - prev_time_mask[t]) + transition_sample * prev_time_mask[t]) * \
                         subject_mask[t]

    return sample + noise


def mixture_random_without_self_dependency(initial_mean: np.ndarray,
                                           sigma: np.ndarray,
                                           mixture_weights: np.ndarray,
                                           coordination: np.ndarray,
                                           prev_time: np.ndarray,
                                           prev_time_mask: np.ndarray,
                                           subject_mask: np.ndarray,
                                           num_subjects: int,
                                           dim_value: int,
                                           rng: Optional[np.random.Generator] = None,
                                           size: Optional[Tuple[int]] = None) -> np.ndarray:
    num_time_steps = coordination.shape[-1]
    noise = rng.normal(loc=0, scale=1, size=size) * sigma

    # We sample the influencers in each time step using the mixture weights
    influencers = []
    for subject in range(num_subjects):
        probs = np.insert(mixture_weights[0], subject, 1)
        influencers.append(rng.choice(a=np.arange(num_subjects), p=probs, size=num_time_steps))
    influencers = np.array(influencers)

    sample = np.zeros_like(noise)
    prior_sample = rng.normal(loc=initial_mean, scale=sigma, size=(num_subjects, dim_value))
    for t in np.arange(1, num_time_steps):
        # Previous sample from a different individual
        D = sample[..., prev_time[t]][influencers[..., t]]

        mean = ((D - initial_mean) * coordination[t] + initial_mean)

        transition_sample = rng.normal(loc=mean, scale=sigma)

        sample[..., t] = (prior_sample * (1 - prev_time_mask[t]) + transition_sample * prev_time_mask[t]) * \
                         subject_mask[t]

    return sample + noise


class MixtureComponentParameters:

    def __init__(self):
        self.mean_a0 = None
        self.sd_aa = None
        self.mixture_weights = None

    def reset(self):
        self.mean_a0 = None
        self.sd_aa = None
        self.mixture_weights = None


class MixtureComponentSamples:

    def __init__(self):
        self.values = np.array([])

        # 1 for time steps in which the component exists, 0 otherwise.
        self.mask = np.array([])

        # Time indices indicating the previous occurrence of the component produced by the subjects. Mixture compo-
        # nents assumes observations are continuous and measurable for all subjects periodically in a specific time-
        # scale. The variable below, maps from the coordination scale to the component's scale.
        self.prev_time = np.array([])


class MixtureComponent:

    def __init__(self, uuid: str, num_subjects: int, dim_value: int, self_dependent: bool):
        self.uuid = uuid
        self.num_subjects = num_subjects
        self.dim_value = dim_value
        self.self_dependent = self_dependent

        self.parameters = MixtureComponentParameters()

    def draw_samples(self, num_series: int, num_time_steps: int,
                     seed: Optional[int], relative_frequency: float,
                     coordination: np.ndarray) -> MixtureComponentSamples:

        # assert self.num_subjects == self.parameters.mixture_weights.shape[0]
        # assert (self.num_subjects - 1) == self.parameters.mixture_weights.shape[1]
        # assert self.num_subjects == self.parameters.mean_a0.shape[0]
        # assert self.num_subjects == self.parameters.sd_aa.shape[0]
        # assert self.dim_value == self.parameters.mean_a0.shape[1]
        # assert self.dim_value == self.parameters.sd_aa.shape[1]

        set_random_seed(seed)

        samples = MixtureComponentSamples()

        samples.values = np.zeros((num_series, self.num_subjects, self.dim_value, num_time_steps))
        samples.mask = np.zeros(shape=(num_series, num_time_steps))
        samples.prev_time = np.full(shape=(num_series, num_time_steps), fill_value=-1)

        # Sample influencers in each time step
        influencers = []
        for subject in range(self.num_subjects):
            probs = np.insert(self.parameters.mixture_weights[0], subject, 0)
            influencers.append(
                np.random.choice(a=np.arange(self.num_subjects), p=probs, size=(num_series, num_time_steps)))
        influencers = np.array(influencers).swapaxes(0, 1)

        for t in range(num_time_steps):
            if (t + 1) == relative_frequency:
                samples.values[..., 0] = norm(loc=self.parameters.mean_a0,
                                              scale=self.parameters.sd_aa).rvs(
                    size=(num_series, self.num_subjects, self.dim_value))
                samples.mask[..., t] = 1
            elif (t + 1) % relative_frequency == 0:
                samples.mask[..., t] = 1
                samples.prev_time[..., t] = t - relative_frequency

                C = coordination[:, t][:, None]
                P = samples.values[..., samples.prev_time[..., t]][..., 0]
                D = P[:, influencers[..., t]][0]

                mean = (D - P) * C + P

                samples.values[..., t] = norm(loc=mean, scale=self.parameters.sd_aa).rvs()

                #
                #
                #
                #
                # for subject1 in range(self.num_subjects):
                #     if self.self_dependent:
                #         S = samples.values[:, subject1, :, samples.prev_time[:, t]][:, 0]  # n x d
                #     else:
                #         S = self.parameters.mean_a0
                #
                #     samples_from_mixture = []
                #     for subject2 in range(self.num_subjects):
                #         if subject1 == subject2:
                #             continue
                #
                #         D = samples.values[:, subject2, :, samples.prev_time[:, t]][:, 0]  # n x d
                #
                #         means = (D - S) * C + S
                #         samples_from_mixture.append(
                #             norm(loc=means, scale=self.parameters.sd_aa).rvs(size=(num_series, self.dim_value)))
                #
                #     # Choose samples from specific influencers according to the mixture weights
                #     influencer_indices = np.random.choice(a=np.arange(self.num_subjects - 1), size=num_series,
                #                                           p=self.parameters.mixture_weights[0])
                #     samples_from_mixture = np.array(samples_from_mixture)
                #
                #     samples.values[:, subject1, :, t] = samples_from_mixture[influencer_indices]

        return samples

    def update_pymc_model(self, coordination: Any, prev_time: ptt.TensorConstant, prev_time_mask: ptt.TensorConstant,
                          subject_mask: ptt.TensorConstant, subject_dimension: str, feature_dimension: str,
                          time_dimension: str, observation: Any) -> Any:

        # mean_a0 = pm.HalfNormal(name=f"mean_a0_{self.uuid}", sigma=1, size=(self.num_subjects, self.dim_value),
        #                         observed=self.parameters.mean_a0)
        # sd_aa = pm.HalfNormal(name=f"sd_aa_{self.uuid}", sigma=1, size=(self.num_subjects, self.dim_value),
        #                       observed=self.parameters.sd_aa)
        # mixture_weights = pm.Dirichlet(name=f"mixture_weights_{self.uuid}",
        #                                a=ptt.ones((self.num_subjects, self.num_subjects - 1)),
        #                                observed=self.parameters.mixture_weights)
        mean_a0 = pm.HalfNormal(name=f"mean_a0_{self.uuid}", sigma=5, size=1,
                                observed=self.parameters.mean_a0)
        sd_aa = pm.HalfNormal(name=f"sd_aa_{self.uuid}", sigma=5, size=1,
                              observed=self.parameters.sd_aa)
        mixture_weights = ptt.constant(self.parameters.mixture_weights)
        # pm.Dirichlet(name=f"mixture_weights_{self.uuid}",
        #                                a=ptt.ones(self.num_subjects - 1),
        #                                size=1,
        #                                observed=self.parameters.mixture_weights)

        expander_aux_mask_matrix = []
        aggregator_aux_mask_matrix = []
        for subject in range(self.num_subjects):
            expander_aux_mask_matrix.append(np.delete(np.eye(self.num_subjects), subject, axis=0))
            aux = np.zeros((self.num_subjects, self.num_subjects - 1))
            aux[subject] = 1
            aux = aux * mixture_weights[0][None, :]
            aggregator_aux_mask_matrix.append(aux)

        expander_aux_mask_matrix = np.concatenate(expander_aux_mask_matrix, axis=0)
        aggregator_aux_mask_matrix = ptt.concatenate(aggregator_aux_mask_matrix, axis=1)

        if self.self_dependent:
            logp_params = (mean_a0,
                           sd_aa,
                           # mixture_weights,
                           coordination,
                           prev_time,
                           prev_time_mask,
                           subject_mask,
                           # ptt.constant(self.num_subjects),
                           # ptt.constant(self.dim_value),
                           ptt.constant(expander_aux_mask_matrix),
                           aggregator_aux_mask_matrix)
            mixture_component = pm.CustomDist(self.uuid, *logp_params, logp=mixture_logp_with_self_dependency,
                                              # random=mixture_random_with_self_dependency,
                                              dims=[subject_dimension, feature_dimension, time_dimension],
                                              observed=observation)
            # prior = pm.Normal.dist(mu=mean_a0, sigma=sd_aa, size=[self.num_subjects, self.dim_value])
            # mixture_component = pm.GaussianRandomWalk(self.uuid,
            #                                           init_dist=prior,
            #                                           sigma=sd_aa,
            #                                           dims=[subject_dimension, feature_dimension, time_dimension])
        else:
            logp_params = (mean_a0,
                           sd_aa,
                           mixture_weights,
                           coordination,
                           prev_time,
                           prev_time_mask,
                           subject_mask,
                           ptt.constant(self.num_subjects),
                           ptt.constant(self.dim_value))

            mixture_component = pm.CustomDist(self.uuid, *logp_params, logp=mixture_logp_without_self_dependency,
                                              # random=mixture_random_without_self_dependency,
                                              dims=[subject_dimension, feature_dimension, time_dimension],
                                              observed=observation)

        return mixture_component
