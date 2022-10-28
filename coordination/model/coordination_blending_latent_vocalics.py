from __future__ import annotations
from typing import Any, Callable, Dict, List, Optional

from datetime import datetime

import numpy as np
from scipy.stats import norm, invgamma
from tqdm import tqdm

from coordination.common.dataset import EvidenceDataset, EvidenceDataSeries
from coordination.component.speech.common import SegmentedUtterance, VocalicsSparseSeries
from coordination.model.particle_filter import Particles
from coordination.model.pgm import PGM, Samples


class LatentVocalicsParticles(Particles):
    coordination: np.ndarray
    latent_vocalics: Dict[str, np.ndarray]

    def _keep_particles_at(self, indices: np.ndarray):
        self.coordination = self.coordination[indices]
        for speaker, latent_vocalics in self.latent_vocalics.items():
            if latent_vocalics is not None:
                self.latent_vocalics[speaker] = latent_vocalics[indices, :]


class LatentVocalicsSamples(Samples):
    coordination: np.ndarray
    latent_vocalics: VocalicsSparseSeries
    observed_vocalics: VocalicsSparseSeries

    @property
    def size(self):
        return self.observed_vocalics.num_time_steps


class LatentVocalicsDataSeries(EvidenceDataSeries):

    def __init__(self, uuid: str, observed_vocalics: VocalicsSparseSeries, coordination: Optional[np.ndarray] = None,
                 latent_vocalics: VocalicsSparseSeries = None):
        super().__init__(uuid)
        self.coordination = coordination
        self.latent_vocalics = latent_vocalics
        self.observed_vocalics = observed_vocalics

    @property
    def num_time_steps(self):
        return self.observed_vocalics.num_time_steps

    @property
    def num_vocalic_features(self):
        return self.observed_vocalics.num_features


class LatentVocalicsDataset(EvidenceDataset):

    def __init__(self, series: List[LatentVocalicsDataSeries]):
        super().__init__(series)

        # Keep a matrix representation of the data for fast processing during training

        self.coordination = None if series[0].coordination is None else np.zeros(
            (len(series), series[0].num_time_steps))

        # n (num samples) x k (num features) x T (num time steps)
        self.latent_vocalics = None if series[0].latent_vocalics is None else np.zeros(
            (len(series), series[0].num_vocalic_features, series[0].num_time_steps))

        self.observed_vocalics = np.zeros((len(series), series[0].num_vocalic_features, series[0].num_time_steps))
        self.vocalics_mask = np.zeros_like(self.observed_vocalics)
        self.previous_vocalics_from_self = np.zeros_like(self.observed_vocalics)
        self.previous_vocalics_from_other = np.zeros_like(self.observed_vocalics)
        self.next_vocalics_from_self = np.ones_like(self.observed_vocalics) * -1
        self.next_vocalics_from_other = np.ones_like(self.observed_vocalics) * -1

        for i, series in enumerate(series):
            if series.coordination is not None:
                self.coordination[i] = series.coordination

            if series.latent_vocalics is not None:
                self.latent_vocalics[i] = series.latent_vocalics

            self.observed_vocalics[i] = series.observed_vocalics.values
            self.vocalics_mask[i] = series.observed_vocalics.mask
            self.previous_vocalics_from_self[i] = np.array(
                [-1 if t is None else t for t in series.observed_vocalics.previous_from_self])
            self.previous_vocalics_from_other[i] = np.array(
                [-1 if t is None else t for t in series.observed_vocalics.previous_from_other])

            for t in series.num_time_steps:
                if self.previous_vocalics_from_self[i, t] >= 0:
                    self.next_vocalics_from_self[self.previous_vocalics_from_self[i, t]] = t

                if self.previous_vocalics_from_other[i, t] >= 0:
                    self.next_vocalics_from_other[self.previous_vocalics_from_other[i, t]] = t


class CoordinationBlendingLatentVocalics(PGM):

    def __init__(self,
                 initial_coordination: float,
                 num_vocalic_features: int,
                 num_speakers: int,
                 a_vcc: float,
                 b_vcc: float,
                 a_va: float,
                 b_va: float,
                 a_vaa: float,
                 b_vaa: float,
                 a_vo: float,
                 b_vo: float,
                 f: Callable = lambda x, s: x,
                 g: Callable = lambda x: x):
        super().__init__()

        self.initial_coordination = initial_coordination
        self.num_vocalic_features = num_vocalic_features
        self.num_speakers = num_speakers
        self.f = f
        self.g = g

        # Parameters of the model
        self.var_cc: Optional[float] = None
        self.var_a: Optional[np.ndarray] = None
        self.var_aa: Optional[np.ndarray] = None
        self.var_o: Optional[np.ndarray] = None

        # Parameters of the prior distributions (Inverse-Gamma) of the variances
        self.a_vcc = a_vcc
        self.b_vcc = b_vcc
        self.a_va = a_va
        self.b_va = b_va
        self.a_vaa = a_vaa
        self.b_vaa = b_vaa
        self.a_vo = a_vo
        self.b_vo = b_vo

        # Samples collected during training
        self.vcc_samples_ = np.array([])
        self.va_samples_ = np.array([])
        self.vaa_samples_ = np.array([])
        self.vo_samples_ = np.array([])
        self.coordination_samples_ = np.array([])
        self.latent_vocalics_samples_ = np.array([])

    # ---------------------------------------------------------
    # SYNTHETIC DATA GENERATION
    # ---------------------------------------------------------

    def sample(self, num_samples: int, num_time_steps: int, seed: Optional[int], time_scale_density: float = 1, *args,
               **kwargs) -> LatentVocalicsSamples:
        """
        Regular ancestral sampling procedure.
        """
        super().sample(num_samples, num_time_steps, seed)

        samples = LatentVocalicsSamples()
        samples.coordination = self._generate_coordination_samples(num_samples, num_time_steps)

        for i in range(num_samples):
            # Subjects A and B
            previous_self = [None] * num_time_steps
            previous_other = [None] * num_time_steps
            previous_time_per_speaker: Dict[str, int] = {}
            latent_vocalics_values = np.zeros((self.num_vocalic_features, num_time_steps))
            observed_vocalics_values = np.zeros((self.num_vocalic_features, num_time_steps))
            utterances: List[Optional[SegmentedUtterance]] = [None] * num_time_steps

            speakers = self._generate_random_speakers(num_time_steps, time_scale_density)
            mask = np.zeros(num_time_steps)

            for t in range(num_time_steps):
                current_coordination = samples.coordination[i, t]

                if speakers[t] is not None:
                    mask[t] = 1

                    previous_time_self = previous_time_per_speaker.get(speakers[t], None)
                    previous_time_other = None
                    for speaker, time in previous_time_per_speaker.items():
                        if speaker == speakers[t]:
                            continue

                        # Most recent vocalics from a different speaker
                        previous_time_other = time if previous_time_other is None else max(previous_time_other, time)

                    previous_value_self = None if previous_time_self is None else latent_vocalics_values[:,
                                                                                  previous_time_self]
                    previous_value_other = None if previous_time_other is None else latent_vocalics_values[:,
                                                                                    previous_time_other]

                    latent_vocalics_values[:, t] = self._sample_latent_vocalics(previous_value_self,
                                                                                previous_value_other,
                                                                                current_coordination)
                    observed_vocalics_values[:, t] = self._sample_observed_vocalics(latent_vocalics_values[:, t])

                    previous_self[t] = previous_time_self
                    previous_other[t] = previous_time_other

                    # Dummy utterance
                    utterances[t] = SegmentedUtterance(f"Speaker {speakers[t]}", datetime.now(), datetime.now(), "")
                    previous_time_per_speaker[speakers[t]] = t

            samples.latent_vocalics = VocalicsSparseSeries(utterances=utterances, previous_from_self=previous_self,
                                                           previous_from_other=previous_other,
                                                           values=latent_vocalics_values, mask=mask)
            samples.observed_vocalics = VocalicsSparseSeries(utterances=utterances, previous_from_self=previous_self,
                                                             previous_from_other=previous_other,
                                                             values=observed_vocalics_values, mask=mask)

        return samples

    def _generate_coordination_samples(self, num_samples: int, num_time_steps: int) -> np.ndarray:
        raise NotImplementedError

    def _generate_random_speakers(self, num_time_steps: int, time_scale_density: float) -> List[Optional[str]]:
        # We always change speakers between time steps when generating vocalics
        transition_matrix = 1 - np.eye(self.num_speakers + 1)

        transition_matrix *= time_scale_density / (self.num_speakers - 1)
        transition_matrix[:-1, -1] = 1 - time_scale_density

        prior = np.ones(self.num_speakers + 1) * time_scale_density / self.num_speakers
        prior[-1] = 1 - time_scale_density

        initial_speaker = np.random.choice(self.num_speakers + 1, 1, p=prior)[0]
        initial_speaker = None if initial_speaker == self.num_speakers else initial_speaker
        speakers = [initial_speaker]

        for t in range(1, num_time_steps):
            probabilities = transition_matrix[self.num_speakers] if speakers[t - 1] is None else transition_matrix[
                speakers[t - 1]]
            speaker = np.random.choice(self.num_speakers + 1, 1, p=probabilities)[0]
            speaker = None if speaker == self.num_speakers else speaker
            speakers.append(speaker)

        return speakers

    def _sample_latent_vocalics(self, previous_self: Optional[float], previous_other: Optional[float],
                                coordination: float) -> np.ndarray:
        if previous_other is None:
            if previous_self is None:
                distribution = norm(loc=0, scale=np.sqrt(self.var_a))
            else:
                distribution = norm(loc=previous_self, scale=np.sqrt(self.var_aa))
        else:
            if previous_self is None:
                D = previous_other
                distribution = norm(loc=D * coordination, scale=np.sqrt(self.var_aa))
            else:
                D = previous_other - previous_self
                distribution = norm(loc=D * coordination + previous_self, scale=np.sqrt(self.var_aa))

        return distribution.rvs()

    def _sample_observed_vocalics(self, latent_vocalics: np.array) -> np.ndarray:
        return norm(loc=latent_vocalics, scale=np.sqrt(self.var_o)).rvs()

    # ---------------------------------------------------------
    # PARAMETER ESTIMATION
    # ---------------------------------------------------------

    def _initialize_gibbs(self, burn_in: int, evidence: LatentVocalicsDataset):
        super()._initialize_gibbs(burn_in, evidence)

        # History of samples in each Gibbs step
        self.vcc_samples_ = np.zeros(burn_in + 1)
        self.va_samples_ = np.zeros(burn_in + 1)
        self.vaa_samples_ = np.zeros(burn_in + 1)
        self.vo_samples_ = np.zeros(burn_in + 1)
        self.coordination_samples_ = np.zeros((burn_in + 1, evidence.num_trials, evidence.num_time_steps))
        self.latent_vocalics_samples_ = np.zeros(
            (burn_in + 1, evidence.num_trials, self.num_vocalic_features, evidence.num_time_steps))

        # 1. Latent variables and parameter initialization
        if evidence.coordination is None:
            self.coordination_samples_[0] = norm(loc=np.zeros((evidence.num_trials, evidence.num_time_steps)),
                                                 scale=0.1).rvs()
            self.coordination_samples_[0, :, 0] = self.initial_coordination
        else:
            self.coordination_samples_[0] = evidence.coordination

        if evidence.latent_vocalics is None:
            self.latent_vocalics_samples_[0] = norm(
                loc=np.zeros((evidence.num_trials, self.num_vocalic_features, evidence.num_time_steps)),
                scale=1).rvs()
        else:
            self.latent_vocalics_samples_[0] = evidence.latent_vocalics

        if self.var_cc is None:
            self.vcc_samples_[0] = invgamma(a=self.a_vcc, scale=self.b_vcc).rvs()
        else:
            self.vcc_samples_[0] = self.var_cc

        if self.var_a is None:
            self.va_samples_[0] = invgamma(a=self.a_va, scale=self.b_va).rvs()
        else:
            self.va_samples_[0] = self.var_a

        if self.var_aa is None:
            self.vaa_samples_[0] = invgamma(a=self.a_vaa, scale=self.b_vaa).rvs()
        else:
            self.vaa_samples_[0] = self.var_aa

        if self.var_o is None:
            self.vo_samples_[0] = invgamma(a=self.a_vo, scale=self.b_vo).rvs()
        else:
            self.vo_samples_[0] = self.var_o

    def _compute_joint_loglikelihood_at(self, gibbs_step: int, evidence: LatentVocalicsDataset) -> float:
        sa = np.sqrt(self.va_samples_[gibbs_step])
        saa = np.sqrt(self.vaa_samples_[gibbs_step])
        so = np.sqrt(self.vo_samples_[gibbs_step])

        ll = self._compute_coordination_transition_loglikelihood_at(gibbs_step)
        coordination = self.coordination_samples_[gibbs_step]
        latent_vocalics = self.latent_vocalics_samples_[gibbs_step]
        for t in range(evidence.num_time_steps):
            C = coordination[:, t][:, np.newaxis]

            # n x k
            V = latent_vocalics[:, :, t]

            # n x 1
            M = evidence.vocalics_mask[:, t][:, np.newaxis]

            # Vs (n x k) will have the values of vocalics from the same speaker per trial
            A = latent_vocalics[range(evidence.num_trials), :, evidence.previous_vocalics_from_self[:, t]]

            # Mask with 1 in the cells in which there are previous vocalics from the same speaker and 0 otherwise
            Ma = np.where(evidence.previous_vocalics_from_self[:, t] >= 0, 1, 0)[:, np.newaxis]

            # Vo (n x k) will have the values of vocalics from other speaker per trial
            B = latent_vocalics[range(evidence.num_trials), :, evidence.previous_vocalics_from_other[:, t]]

            # Mask with 1 in the cells in which there are previous vocalics from another speaker and 0 otherwise
            Mb = np.where(evidence.previous_vocalics_from_other[:, t] >= 0, 1, 0)[:, np.newaxis]

            # Use variance from prior if there are no previous vocalics from any speaker
            v = np.where((1 - Ma) * (1 - Mb) == 1, sa, saa)

            # Clipping has no effect in models that do not sample coordination outside the range [0, 1].
            means = (B - A) * Mb * np.clip(C, a_min=0, a_max=1) + A * Ma

            # Do not count LL if no speaker is talking at time t (mask M tells us that)
            ll += (norm(loc=means, scale=np.sqrt(v)).logpdf(V) * M).sum()

            # LL from latent to observed vocalics
            ll += (norm(loc=V, scale=so).logpdf(evidence.observed_vocalics[:, :, t]) * M).sum()

        return ll

    def _compute_coordination_transition_loglikelihood_at(self, gibbs_step: int, evidence: LatentVocalicsDataSeries):
        raise NotImplementedError

    def _gibbs_step(self, gibbs_step: int, evidence: LatentVocalicsDataset, time_steps: np.ndarray, job_num: int):
        if evidence.coordination is None:
            coordination = self._sample_coordination_on_fit(gibbs_step, evidence, time_steps, job_num)
        else:
            coordination = self.coordination_samples_[gibbs_step - 1].copy()

        if evidence.latent_vocalics is None:
            latent_vocalics = self._sample_latent_vocalics_on_fit(coordination, gibbs_step, evidence, time_steps,
                                                                  job_num)
        else:
            latent_vocalics = self.latent_vocalics_samples_[gibbs_step - 1].copy()

        return coordination[:, time_steps], latent_vocalics[:, time_steps]

    def _sample_coordination_on_fit(self, gibbs_step: int, evidence: LatentVocalicsDataset, time_steps: np.ndarray,
                                    job_num: int) -> np.ndarray:
        raise NotImplementedError

    def _sample_latent_vocalics_on_fit(self, coordination: np.ndarray, gibbs_step: int, evidence: LatentVocalicsDataset,
                                       time_steps: np.ndarray, job_num: int) -> np.ndarray:

        va = self.va_samples_[gibbs_step]
        vaa = self.vaa_samples_[gibbs_step]
        vo = self.vo_samples_[gibbs_step]

        latent_vocalics = self.latent_vocalics_samples_[gibbs_step - 1].copy()
        trials_indices = np.arange(evidence.num_trials)
        for t in tqdm(time_steps, desc="Sampling Latent Vocalics", position=job_num, leave=False):
            C1 = coordination[:, t][:, np.newaxis]
            M1 = evidence.vocalics_mask[:, t][:, np.newaxis]
            A1 = latent_vocalics[trials_indices, :, evidence.previous_vocalics_from_self[:, t]]
            Ma1 = np.where(evidence.previous_vocalics_from_self[:, t] >= 0, 1, 0)[:, np.newaxis]
            B1 = latent_vocalics[trials_indices, :, evidence.previous_vocalics_from_other[:, t]]
            Mb1 = np.where(evidence.previous_vocalics_from_other[:, t] >= 0, 1, 0)[:, np.newaxis]

            # Time steps in which the next speaker is the same
            t2a = evidence.next_vocalics_from_self[:, t]
            C2a = coordination[trials_indices, t2a][:, np.newaxis]
            V2a = latent_vocalics[trials_indices, :, t2a]
            M2a = evidence.vocalics_mask[trials_indices, t2a][:, np.newaxis]
            Ma2a = np.where(t2a >= 0, 1, 0)[:, np.newaxis]
            B2a = latent_vocalics[trials_indices, :, evidence.previous_vocalics_from_other[trials_indices, t2a]]
            Mb2a = np.where(evidence.previous_vocalics_from_other[trials_indices, t2a] >= 0, 1, 0)[:, np.newaxis]

            # Time steps in which the next speaker is different
            t2b = evidence.next_vocalics_from_other[:, t]
            C2b = coordination[trials_indices, t2b][:, np.newaxis]
            V2b = latent_vocalics[trials_indices, :, t2b]
            M2b = evidence.vocalics_mask[trials_indices, t2b][:, np.newaxis]
            A2b = latent_vocalics[trials_indices, :, evidence.previous_vocalics_from_self[trials_indices, t2b]]
            Ma2b = np.where(evidence.previous_vocalics_from_self[trials_indices, t2b] >= 0, 1, 0)[:, np.newaxis]
            Mb2b = np.where(t2b >= 0, 1, 0)[:, np.newaxis]

            m1 = (B1 - A1) * C1 * Mb1 + A1 * Ma1
            v1 = np.where((1 - Ma1) * (1 - Mb1) == 1, va, vaa)

            m2a = B2a * C2a * Mb2a - V2a
            h2a = C2a * Mb2a - Ma2a
            v2a = np.where((1 - Ma2a) * (1 - Mb2a) == 1, va, vaa)

            m2b = (Ma2b + C2b * Mb2b) * A2b - V2b
            h2b = - C2b * Mb2b
            v2b = np.where((1 - Ma2b) * (1 - Mb2b) == 1, va, vaa)

            m3 = ((m1 / v1) + (m2a * h2a * M2a / v2a) + (m2b * h2b * M2b / v2b) + (
                    evidence.observed_vocalics[:, :, t] / vo)) * M1
            v_inv = ((1 / v1) + ((h2a * M2a) ** 2 / v2a) + ((h2b * M2b) ** 2 / v2b) + (1 / vo)) * M1

            v = np.where(M1 == 0, 0, 1 / v_inv)

            if t == 0:
                m = np.where(M1 == 0, -1, m3 / v)
            else:
                # Repeat previous latent vocalics if no one is talking at time t
                m = np.where(M1 == 0, latent_vocalics[:, :, t - 1], m3 / v)

            latent_vocalics[:, :, t] = norm(loc=m, scale=np.sqrt(v)).rvs()

        return latent_vocalics

    def _retain_samples_from_latent(self, gibbs_step: int, latents: Any, time_steps: np.ndarray):
        """
        The only latent variable return by _gibbs_step is a state variable
        """
        self.coordination_samples_[gibbs_step, :, time_steps] = latents[0].T
        self.latent_vocalics_samples_[gibbs_step, :, time_steps] = latents[1].T

    def _update_latent_parameters(self, gibbs_step: int, evidence: LatentVocalicsDataset):
        self._update_latent_parameters_coordination(gibbs_step, evidence)

        # Variance of the latent vocalics prior
        if self.var_a is None:
            first_time_steps = np.minimum(np.where(evidence.next_vocalics_from_self[0] == -1, evidence.num_time_steps,
                                                   evidence.next_vocalics_from_self[0]),
                                          np.where(evidence.next_vocalics_from_other[0] == -1, evidence.num_time_steps,
                                                   evidence.next_vocalics_from_other[0]))
            time_steps = first_time_steps[first_time_steps < evidence.num_time_steps]
            first_latent_vocalics = self.latent_vocalics_samples_[gibbs_step][:, :, time_steps].T

            a = self.a_va + len(first_latent_vocalics) / 2
            b = self.b_va + np.square(first_latent_vocalics).sum() / 2
            self.va_samples_[gibbs_step] = invgamma(a=a, scale=b).rvs()
        else:
            # Given
            self.va_samples_[gibbs_step] = self.var_a

        # Variance of the latent vocalics transition
        if self.var_aa is None:
            M = evidence.vocalics_mask
            Ma = np.where(evidence.previous_vocalics_from_self == -1, 0, 1)
            Mb = np.where(evidence.previous_vocalics_from_other == -1, 0, 1)

            # All times in which there was vocalics and either previous vocalics from the same speaker or a different
            # one
            Ml = (M * (1 - (1 - Ma) * (1 - Mb)))
            V = self.latent_vocalics_samples_[gibbs_step]
            A = self.latent_vocalics_samples_[gibbs_step][np.arange(evidence.num_trials)[:, np.newaxis], :,
                evidence.previous_vocalics_from_self][:, np.newaxis, :]
            B = self.latent_vocalics_samples_[gibbs_step][np.arange(evidence.num_trials)[:, np.newaxis], :,
                evidence.previous_vocalics_from_other][:, np.newaxis, :]

            x = (V - (B - A) * self.coordination_samples_[gibbs_step][:, np.newaxis, :] * Mb + A * Ma) * Ml

            a = self.a_vaa + Ml.sum() / 2
            b = self.b_vaa + np.square(x).sum() / 2
            self.vaa_samples_[gibbs_step] = invgamma(a=a, scale=b).rvs()
        else:
            # Given
            self.vaa_samples_[gibbs_step] = self.var_aa

        # Variance of the vocalics emission
        if self.var_o is None:
            M = evidence.vocalics_mask

            V = self.latent_vocalics_samples_[gibbs_step]
            x = (V - evidence.observed_vocalics) * M

            a = self.a_vo + M.sum() / 2
            b = self.b_vo + np.square(x).sum() / 2
            self.vo_samples_[gibbs_step] = invgamma(a=a, scale=b).rvs()
        else:
            # Given
            self.vo_samples_[gibbs_step] = self.var_o

    def _update_latent_parameters_coordination(self, gibbs_step: int, evidence: EvidenceDataset):
        # Variance of the State Transition
        # if self.var_cc is None:
        #     # TODO - sample var_cc
        #     pass
        #     # a = self.a_vst + evidence.num_trials * (evidence.num_time_steps - 1) / 2
        #     # b = self.b_vst + np.square(
        #     #     self.state_samples_[gibbs_step, :, 1:] - self.state_samples_[gibbs_step, :,
        #     #                                              :evidence.num_time_steps - 1]).sum() / 2
        #     # self.vst_samples_[gibbs_step] = invgamma(a=a, scale=b).rvs()
        # else:
        #     # Given
        #     self.vcc_samples_[gibbs_step] = self.var_cc
        raise NotImplementedError

    def _retain_parameters(self):
        self.var_cc = self.vcc_samples_[-1]
        self.var_a = self.va_samples_[-1]
        self.var_aa = self.vaa_samples_[-1]
        self.var_o = self.vo_samples_[-1]

    # ---------------------------------------------------------
    # INFERENCE
    # ---------------------------------------------------------

    def _summarize_particles(self, particles: List[Particles]) -> np.ndarray:
        raise NotImplementedError

    def _sample_from_prior(self, num_particles: int, series: LatentVocalicsDataSeries) -> Particles:
        new_particles = self._create_new_particles()
        self._sample_coordination_from_prior(num_particles, new_particles)
        self._sample_vocalics_from_prior(num_particles, series, new_particles)

        return new_particles

    def _sample_coordination_from_prior(self, num_particles: int, new_particles: LatentVocalicsParticles):
        new_particles.coordination = np.ones(num_particles) * self.initial_coordination

    def _sample_vocalics_from_prior(self, num_particles: int, series: LatentVocalicsDataSeries,
                                    new_particles: LatentVocalicsParticles):
        new_particles.latent_vocalics = {subject: None for subject in series.observed_vocalics.subjects}
        if series.observed_vocalics.mask[0] == 1:
            speaker = series.observed_vocalics.utterances[0].subject_id
            mean = np.zeros((num_particles, series.observed_vocalics.num_features))
            new_particles.latent_vocalics[speaker] = norm(loc=mean, scale=np.sqrt(self.var_a)).rvs()

    def _sample_from_transition_to(self, time_step: int, states: List[LatentVocalicsParticles],
                                   series: LatentVocalicsDataSeries) -> LatentVocalicsParticles:

        new_particles = self._create_new_particles()
        self._sample_coordination_from_transition(states[time_step - 1], new_particles)
        self._sample_vocalics_from_transition_to(time_step, states[time_step - 1], new_particles, series)

        return new_particles

    def _sample_vocalics_from_transition_to(self, time_step: int, previous_particles: LatentVocalicsParticles,
                                            new_particles: LatentVocalicsParticles, series: LatentVocalicsDataSeries):
        new_particles.latent_vocalics = previous_particles.latent_vocalics.copy()
        if series.observed_vocalics.mask[time_step] == 1:
            speaker = series.observed_vocalics.utterances[time_step].subject_id

            A = previous_particles.latent_vocalics[speaker]
            A = self.f(A, 0) if A is not None else np.zeros_like(previous_particles.latent_vocalics)

            if series.observed_vocalics.previous_from_other[time_step] is None:
                if series.observed_vocalics.previous_from_self[time_step] is None:
                    new_particles.latent_vocalics[speaker] = norm(loc=A, scale=np.sqrt(self.var_a)).rvs()
                else:
                    new_particles.latent_vocalics[speaker] = norm(loc=A, scale=np.sqrt(self.var_aa)).rvs()
            else:
                other_speaker = series.observed_vocalics.utterances[
                    series.observed_vocalics.previous_from_other[time_step]].subject_id
                B = self.f(previous_particles.latent_vocalics[other_speaker], 1)
                mean = (B - A) * new_particles.coordination[:, np.newaxis] + A
                new_particles.latent_vocalics[speaker] = norm(loc=mean, scale=np.sqrt(self.var_aa)).rvs()

    def _calculate_evidence_log_likelihood_at(self, time_step: int, states: List[LatentVocalicsParticles],
                                              series: LatentVocalicsDataSeries):
        if series.observed_vocalics.mask[time_step] == 1:
            speaker = series.observed_vocalics.utterances[time_step].subject_id
            Vt = states[time_step].latent_vocalics[speaker]
            Ot = series.observed_vocalics.values[:, time_step]
            log_likelihoods = norm(loc=self.g(Vt), scale=np.sqrt(self.var_o)).logpdf(Ot).sum(axis=1)
        else:
            log_likelihoods = 0

        return log_likelihoods

    def _resample_at(self, time_step: int, series: LatentVocalicsDataSeries):
        return series.observed_vocalics.mask[time_step] == 1 and series.observed_vocalics.previous_from_other[
            time_step] is not None

    def _sample_coordination_from_transition(self, previous_particles: LatentVocalicsParticles,
                                             new_particles: LatentVocalicsParticles) -> Particles:
        raise NotImplementedError

    def _create_new_particles(self) -> LatentVocalicsParticles:
        return LatentVocalicsParticles()
