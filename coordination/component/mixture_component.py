import math
from typing import Any, Callable, List, Optional, Tuple

from functools import partial
import itertools
import numpy as np
import pymc as pm
import pytensor.tensor as ptt
from scipy.stats import norm

from coordination.common.activation_function import ActivationFunction
from coordination.common.utils import set_random_seed
from coordination.model.parametrization import Parameter, HalfNormalParameterPrior, DirichletParameterPrior, \
    NormalParameterPrior
from coordination.component.utils import feed_forward_logp_f, feed_forward_random_f


def apply_lags(lag: Any, data: Any):
    if isinstance(lag, np.ndarray):
        rows, column_indices = np.ogrid[:data.shape[0], :data.shape[1]]

        # Use always a negative shift, so that column_indices are valid.
        # (could also use module operation)
        r = lag.copy()
        r[r < 0] += data.shape[1]
        column_indices = column_indices - r[:, np.newaxis]

        return data[rows, column_indices]
    else:
        rows, column_indices = ptt.ogrid[:data.shape[0], :data.shape[1]]

        # Use always a negative shift, so that column_indices are valid.
        # (could also use module operation)
        r = ptt.cast(ptt.switch((lag < 0), lag + data.shape[1], lag), "int32")
        column_indices = column_indices - r[:, np.newaxis]

        return data[rows, column_indices]


def mixture_logp_with_self_dependency(mixture_component: Any,
                                      initial_mean: Any,
                                      sigma: Any,
                                      mixture_weights: Any,
                                      coordination: Any,
                                      lag: Any,
                                      input_layer_f: Any,
                                      hidden_layers_f: Any,
                                      output_layer_f: Any,
                                      activation_function_number_f: ptt.TensorConstant,
                                      expander_aux_mask_matrix: ptt.TensorConstant,
                                      aggregation_aux_mask_matrix: ptt.TensorVariable,
                                      coordination_mask: ptt.TensorConstant):
    num_subjects = mixture_component.shape[0]
    num_features = mixture_component.shape[1]
    num_time_steps = mixture_component.shape[2]

    # Log probability due to the initial time step in the component's scale.
    total_logp = pm.logp(pm.Normal.dist(mu=initial_mean, sigma=sigma, shape=(num_subjects, num_features)),
                         mixture_component[..., 0]).sum()

    # D contains the values from other individuals for each individual
    D = ptt.tensordot(expander_aux_mask_matrix, mixture_component, axes=(1, 0))  # s * (s-1) x d x t

    # Repeat lag values across features.
    lag_extended = ptt.repeat(lag, repeats=num_features, axis=0)

    # Shift data according to the lags for each pair of subjects. We will use D as the previous value from different
    # subjects for every subject in the component.
    D = apply_lags(lag_extended, D.reshape((D.shape[0] * D.shape[1], num_time_steps))).reshape(
        D.shape)

    # Fit a function f(.) over the pairs to correct anti-symmetry.
    D = feed_forward_logp_f(input_data=D.reshape((num_subjects * num_features, num_time_steps)),
                            input_layer_f=input_layer_f,
                            hidden_layers_f=hidden_layers_f,
                            output_layer_f=output_layer_f,
                            activation_function_number_f=activation_function_number_f).reshape(D.shape)

    # Discard last time step because it is not previous to any other time step.
    D = D[..., :-1]

    # Previous values from every subject
    P = mixture_component[..., :-1]  # s x d x t-1

    # Previous values from the same subjects
    S_extended = ptt.repeat(P, repeats=(num_subjects - 1), axis=0)

    # Current values from each subject. We extend S and point such that they match the dimensions of D.
    point_extended = ptt.repeat(mixture_component[..., 1:], repeats=(num_subjects - 1), axis=0)

    # The mask will zero out dependencies on D if we have shifts caused by latent lags. In that case, we cannot infer
    # coordination if the values do not exist on all the subjects because of gaps introduced by the shift. So we can
    # only infer the next value of the latent value from its previous one on the same subject,
    C = coordination[None, None, 1:]  # 1 x 1 x t-1
    mean = (D - S_extended) * C * coordination_mask[..., :-1] + S_extended

    sd = ptt.repeat(sigma, repeats=(num_subjects - 1), axis=0)[:, :, None]

    pdf = pm.math.exp(pm.logp(pm.Normal.dist(mu=mean, sigma=sd, shape=D.shape), point_extended))
    # Compute dot product along the second dimension of pdf
    total_logp += pm.math.log(ptt.tensordot(aggregation_aux_mask_matrix, pdf, axes=(1, 0))).sum()

    return total_logp


def mixture_logp_without_self_dependency(mixture_component: Any,
                                         initial_mean: Any,
                                         sigma: Any,
                                         mixture_weights: Any,
                                         coordination: Any,
                                         lag: Any,
                                         input_layer_f: Any,
                                         hidden_layers_f: Any,
                                         output_layer_f: Any,
                                         activation_function_number_f: ptt.TensorConstant,
                                         expander_aux_mask_matrix: ptt.TensorConstant,
                                         aggregation_aux_mask_matrix: ptt.TensorVariable,
                                         coordination_mask: ptt.TensorConstant):
    num_subjects = mixture_component.shape[0]
    num_features = mixture_component.shape[1]
    num_time_steps = mixture_component.shape[2]

    # Log probability due to the initial time step in the component's scale.
    total_logp = pm.logp(pm.Normal.dist(mu=initial_mean, sigma=sigma, shape=(num_subjects, num_features)),
                         mixture_component[..., 0]).sum()

    # D contains the values from other individuals for each individual
    D = ptt.tensordot(expander_aux_mask_matrix, mixture_component, axes=(1, 0))  # s * (s-1) x d x t

    # Repeat lag values across features.
    lag_extended = ptt.repeat(lag, repeats=num_features, axis=0)

    # Shift data according to the lags for each pair of subjects. We will use D as the previous value from different
    # subjects for every subject in the component.
    D = apply_lags(lag_extended, D.reshape((D.shape[0] * D.shape[1], num_time_steps))).reshape(
        D.shape)

    # Fit a function f(.) over the pairs to correct anti-symmetry.
    D = feed_forward_logp_f(input_data=D.reshape((num_subjects * num_features, num_time_steps)),
                            input_layer_f=input_layer_f,
                            hidden_layers_f=hidden_layers_f,
                            output_layer_f=output_layer_f,
                            activation_function_number_f=activation_function_number_f).reshape(D.shape)

    # Discard last time step because it is not previous to any other time step.
    D = D[..., :-1]

    # Fixed value given by the initial mean for each subject. No self-dependency.
    S_extended = ptt.repeat(initial_mean[:, :, None], repeats=(num_subjects - 1), axis=0)

    # Current values from each subject. We extend S and point such that they match the dimensions of D.
    point_extended = ptt.repeat(mixture_component[..., 1:], repeats=(num_subjects - 1), axis=0)

    # The mask will zero out dependencies on D if we have shifts caused by latent lags. In that case, we cannot infer
    # coordination if the values do not exist on all the subjects because of gaps introduced by the shift. So we can
    # only infer the next value of the latent value from its previous one on the same subject,
    C = coordination[None, None, 1:]  # 1 x 1 x t-1
    mean = (D - S_extended) * C * coordination_mask[..., :-1] + S_extended

    sd = ptt.repeat(sigma, repeats=(num_subjects - 1), axis=0)[:, :, None]

    pdf = pm.math.exp(pm.logp(pm.Normal.dist(mu=mean, sigma=sd, shape=D.shape), point_extended))
    # Compute dot product along the second dimension of pdf
    total_logp += pm.math.log(ptt.tensordot(aggregation_aux_mask_matrix, pdf, axes=(1, 0))).sum()

    return total_logp


def mixture_random_with_self_dependency(initial_mean: np.ndarray,
                                        sigma: np.ndarray,
                                        mixture_weights: np.ndarray,
                                        coordination: np.ndarray,
                                        lag: np.ndarray,
                                        input_layer_f: np.ndarray,
                                        hidden_layers_f: np.ndarray,
                                        output_layer_f: np.ndarray,
                                        activation_function_number_f: int,
                                        expander_aux_mask_matrix: np.ndarray,
                                        aggregation_aux_mask_matrix: np.ndarray,
                                        mixture_mask: np.ndarray,
                                        num_subjects: int,
                                        dim_value: int,
                                        rng: Optional[np.random.Generator] = None,
                                        size: Optional[Tuple[int]] = None) -> np.ndarray:
    num_time_steps = coordination.shape[-1]

    noise = rng.normal(loc=0, scale=1, size=size) * sigma[:, :, None]

    # We sample the influencers in each time step using the mixture weights
    influencers = []
    for subject in range(num_subjects):
        probs = np.insert(mixture_weights[subject], subject, 0)
        influencers.append(rng.choice(a=np.arange(num_subjects), p=probs, size=num_time_steps))
    influencers = np.array(influencers)

    sample = np.zeros_like(noise)
    prior_sample = rng.normal(loc=initial_mean, scale=sigma, size=(num_subjects, dim_value))
    sample[..., 0] = prior_sample

    # TODO - Add treatment for lag
    activation = ActivationFunction.from_numpy_number(activation_function_number_f)
    for t in np.arange(1, num_time_steps):
        # Previous sample from a different individual
        D = sample[..., t - 1][influencers[..., t]]
        D = feed_forward_random_f(input_data=D.flatten()[:, None],
                                  input_layer_f=input_layer_f,
                                  hidden_layers_f=hidden_layers_f,
                                  output_layer_f=output_layer_f,
                                  activation=activation)[:, 0].reshape(D.shape)

        # Previous sample from the same individual
        S = sample[..., t - 1]

        mean = ((D - S) * coordination[t] + S)

        transition_sample = rng.normal(loc=mean, scale=sigma)

        sample[..., t] = transition_sample

    return sample + noise


def mixture_random_without_self_dependency(initial_mean: np.ndarray,
                                           sigma: np.ndarray,
                                           mixture_weights: np.ndarray,
                                           coordination: np.ndarray,
                                           lag: np.ndarray,
                                           input_layer_f: np.ndarray,
                                           hidden_layers_f: np.ndarray,
                                           output_layer_f: np.ndarray,
                                           activation_function_number_f: int,
                                           expander_aux_mask_matrix: np.ndarray,
                                           aggregation_aux_mask_matrix: np.ndarray,
                                           mixture_mask: np.ndarray,
                                           num_subjects: int,
                                           dim_value: int,
                                           rng: Optional[np.random.Generator] = None,
                                           size: Optional[Tuple[int]] = None) -> np.ndarray:
    num_time_steps = coordination.shape[-1]

    noise = rng.normal(loc=0, scale=1, size=size) * sigma[:, :, None]

    # We sample the influencers in each time step using the mixture weights
    influencers = []
    for subject in range(num_subjects):
        probs = np.insert(mixture_weights[subject], subject, 0)
        influencers.append(rng.choice(a=np.arange(num_subjects), p=probs, size=num_time_steps))
    influencers = np.array(influencers)

    sample = np.zeros_like(noise)
    prior_sample = rng.normal(loc=initial_mean, scale=sigma, size=(num_subjects, dim_value))
    sample[..., 0] = prior_sample

    # No self-dependency. The transition distribution is a blending between the previous value from another individual,
    # and a fixed mean.
    S = initial_mean
    # TODO - Add treatment for lag
    activation = ActivationFunction.from_numpy_number(activation_function_number_f)
    for t in np.arange(1, num_time_steps):
        # Previous sample from a different individual
        D = sample[..., t - 1][influencers[..., t]]
        D = feed_forward_random_f(input_data=D.flatten()[:, None],
                                  input_layer_f=input_layer_f,
                                  hidden_layers_f=hidden_layers_f,
                                  output_layer_f=output_layer_f,
                                  activation=activation)[:, 0].reshape(D.shape)

        mean = ((D - S) * coordination[t] + S)

        transition_sample = rng.normal(loc=mean, scale=sigma)

        sample[..., t] = transition_sample

    return sample + noise


class MixtureComponentParameters:

    def __init__(self, mean_mean_a0: np.ndarray, sd_mean_a0: np.ndarray, sd_sd_aa: np.ndarray,
                 a_mixture_weights: np.ndarray, mean_weights_f: float, sd_weights_f: float):
        self.mean_a0 = Parameter(NormalParameterPrior(mean_mean_a0, sd_mean_a0))
        self.sd_aa = Parameter(HalfNormalParameterPrior(sd_sd_aa))
        self.mixture_weights = Parameter(DirichletParameterPrior(a_mixture_weights))
        self.weights_f = Parameter(NormalParameterPrior(np.array(mean_weights_f), np.array([sd_weights_f])))

    def clear_values(self):
        self.mean_a0.value = None
        self.sd_aa.value = None
        self.mixture_weights.value = None
        self.weights_f.value = None


class MixtureComponentSamples:

    def __init__(self):
        self.values = np.array([])

        # For each time step in the component's scale, it contains the time step in the coordination scale
        self.time_steps_in_coordination_scale = np.array([])

    @property
    def num_time_steps(self):
        return self.values.shape[-1]


class MixtureComponent:

    def __init__(self, uuid: str, num_subjects: int, dim_value: int, self_dependent: bool, mean_mean_a0: np.ndarray,
                 sd_mean_a0: np.ndarray, sd_sd_aa: np.ndarray, a_mixture_weights: np.ndarray,
                 share_params_across_subjects: bool, share_params_across_features: bool, f: Optional[Callable] = None,
                 mean_weights_f: float = 0, sd_weights_f: float = 1, max_lag: int = 0):

        dim = 1 if share_params_across_features else dim_value
        if share_params_across_subjects:
            assert (dim,) == mean_mean_a0.shape
            assert (dim,) == sd_mean_a0.shape
            assert (dim,) == sd_sd_aa.shape
        else:
            assert (num_subjects, dim) == mean_mean_a0.shape
            assert (num_subjects, dim) == sd_mean_a0.shape
            assert (num_subjects, dim) == sd_sd_aa.shape

        assert (num_subjects, num_subjects - 1) == a_mixture_weights.shape

        self.uuid = uuid
        self.num_subjects = num_subjects
        self.dim_value = dim_value
        self.self_dependent = self_dependent
        self.share_params_across_subjects = share_params_across_subjects
        self.share_params_across_features = share_params_across_features
        self.f = f
        self.max_lag = max_lag

        self.parameters = MixtureComponentParameters(mean_mean_a0=mean_mean_a0,
                                                     sd_mean_a0=sd_mean_a0,
                                                     sd_sd_aa=sd_sd_aa,
                                                     a_mixture_weights=a_mixture_weights,
                                                     mean_weights_f=mean_weights_f,
                                                     sd_weights_f=sd_weights_f)

    @property
    def parameter_names(self) -> List[str]:
        return [
            self.mean_a0_name,
            self.sd_aa_name,
            self.mixture_weights_name
        ]

    @property
    def mean_a0_name(self) -> str:
        return f"mean_a0_{self.uuid}"

    @property
    def sd_aa_name(self) -> str:
        return f"sd_aa_{self.uuid}"

    @property
    def mixture_weights_name(self) -> str:
        return f"mixture_weights_{self.uuid}"

    @property
    def f_nn_weights_name(self) -> str:
        return f"f_nn_weights_{self.uuid}"

    def draw_samples(self, num_series: int, relative_frequency: float,
                     coordination: np.ndarray, seed: Optional[int] = None) -> MixtureComponentSamples:

        dim = 1 if self.share_params_across_features else self.dim_value
        if self.share_params_across_subjects:
            assert (dim,) == self.parameters.mean_a0.value.shape
            assert (dim,) == self.parameters.sd_aa.value.shape
        else:
            assert (self.num_subjects, dim) == self.parameters.mean_a0.value.shape
            assert (self.num_subjects, dim) == self.parameters.sd_aa.value.shape

        assert relative_frequency >= 1
        assert (self.num_subjects, self.num_subjects - 1) == self.parameters.mixture_weights.value.shape

        set_random_seed(seed)

        samples = MixtureComponentSamples()

        # Number of time steps in the component's scale
        num_time_steps_in_cpn_scale = int(coordination.shape[-1] / relative_frequency)
        samples.values = np.zeros((num_series, self.num_subjects, self.dim_value, num_time_steps_in_cpn_scale))
        samples.time_steps_in_coordination_scale = np.full((num_series, num_time_steps_in_cpn_scale), fill_value=-1,
                                                           dtype=int)

        # Sample influencers in each time step
        influencers = []
        for subject in range(self.num_subjects):
            probs = np.insert(self.parameters.mixture_weights.value[subject], subject, 0)
            influencers.append(
                np.random.choice(a=np.arange(self.num_subjects), p=probs,
                                 size=(num_series, num_time_steps_in_cpn_scale)))
        influencers = np.array(influencers).swapaxes(0, 1)

        if self.share_params_across_subjects:
            # Broadcasted across samples, subjects and time
            sd = self.parameters.sd_aa.value[None, None, :]
        else:
            sd = self.parameters.sd_aa.value[None, :]

        for t in range(num_time_steps_in_cpn_scale):
            if t == 0:
                if self.share_params_across_subjects:
                    # Broadcasted across samples, subjects
                    mean = self.parameters.mean_a0.value[None, None, :]
                else:
                    mean = self.parameters.mean_a0.value[None, :]

                samples.values[..., 0] = norm(loc=mean, scale=sd).rvs(
                    size=(num_series, self.num_subjects, self.dim_value))
            else:
                time_in_coord_scale = relative_frequency * t

                C = coordination[:, time_in_coord_scale][:, None]
                P = samples.values[..., t - 1]
                D = P[:, influencers[..., t]][0]

                if self.f is not None:
                    D = self.f(D)

                if self.self_dependent:
                    S = P
                else:
                    if self.share_params_across_subjects:
                        # Broadcasted across samples and subjects
                        S = self.parameters.mean_a0.value[None, None, :]
                    else:
                        S = self.parameters.mean_a0.value[None, :]

                mean = (D - S) * C + S

                samples.values[..., t] = norm(loc=mean, scale=sd).rvs()
                samples.time_steps_in_coordination_scale[..., t] = time_in_coord_scale

        return samples

    def _create_random_parameters(self, mean_a0: Optional[Any] = None, sd_aa: Optional[Any] = None,
                                  mixture_weights: Optional[Any] = None):
        """
        This function creates the initial mean and standard deviation of the serialized component distribution as
        random variables.
        """
        dim = 1 if self.share_params_across_features else self.dim_value
        if self.share_params_across_subjects:
            if mean_a0 is None:
                mean_a0 = pm.Normal(name=self.mean_a0_name, mu=self.parameters.mean_a0.prior.mean,
                                    sigma=self.parameters.mean_a0.prior.sd, size=dim,
                                    observed=self.parameters.mean_a0.value)

            if sd_aa is None:
                sd_aa = pm.HalfNormal(name=self.sd_aa_name, sigma=self.parameters.sd_aa.prior.sd,
                                      size=dim, observed=self.parameters.sd_aa.value)

            mean_a0 = mean_a0[None, :].repeat(self.num_subjects, axis=0)
            sd_aa = sd_aa[None, :].repeat(self.num_subjects, axis=0)
        else:
            if mean_a0 is None:
                mean_a0 = pm.Normal(name=self.mean_a0_name, mu=self.parameters.mean_a0.prior.mean,
                                    sigma=self.parameters.mean_a0.prior.sd, size=(self.num_subjects, dim),
                                    observed=self.parameters.mean_a0.value)
            if sd_aa is None:
                sd_aa = pm.HalfNormal(name=self.sd_aa_name, sigma=self.parameters.sd_aa.prior.sd,
                                      size=(self.num_subjects, dim), observed=self.parameters.sd_aa.value)

        if mixture_weights is None:
            mixture_weights = pm.Dirichlet(name=self.mixture_weights_name,
                                           a=self.parameters.mixture_weights.prior.a,
                                           observed=self.parameters.mixture_weights.value)

        return mean_a0, sd_aa, mixture_weights

    def _create_random_weights_f(self, num_hidden_layers: int, dim_hidden_layer: int, activation_function_name: str):
        """
        This function creates the weights used to fit the function f(.) as random variables. Because the mixture
        component uses a CustomDist, all the arguments of the logp function we pass must be tensors. So, we cannot
        pass a list of tensors from different sizes, otherwise the program will crash when it tries to convert that
        to a single tensor. Therefore, the strategy is to have 3 sets of weights, the first one represents the weights
        in the input layer, the second will be a list of weights with the same dimensions, which represent the weights
        in the hidden layers, and the last one will be weights in the last (output) layer.
        """

        # Gather observations from each layer. If some weights are pre-set, we don't need to infer them.
        if self.parameters.weights_f.value is None:
            observed_weights_f = [None] * 3
        else:
            observed_weights_f = self.parameters.weights_f.value

        # Features * number of subjects + bias term
        input_layer_dim_in = self.dim_value * self.num_subjects + 1
        input_layer_dim_out = dim_hidden_layer

        hidden_layer_dim_in = dim_hidden_layer + 1
        hidden_layer_dim_out = dim_hidden_layer

        output_layer_dim_in = dim_hidden_layer + 1
        output_layer_dim_out = self.dim_value * self.num_subjects

        input_layer = pm.Normal(f"{self.f_nn_weights_name}_in",
                                mu=self.parameters.weights_f.prior.mean,
                                sigma=self.parameters.weights_f.prior.sd,
                                size=(input_layer_dim_in, input_layer_dim_out),
                                observed=observed_weights_f[0])

        hidden_layers = pm.Normal(f"{self.f_nn_weights_name}_hidden",
                                  mu=self.parameters.weights_f.prior.mean,
                                  sigma=self.parameters.weights_f.prior.sd,
                                  size=(num_hidden_layers, hidden_layer_dim_in, hidden_layer_dim_out),
                                  observed=observed_weights_f[1])

        # There's a bug in PyMC 5.0.2 that we cannot pass an argument with more dimensions than the
        # dimension of CustomDist. To work around it, I will join the layer dimension with the input dimension for
        # the hidden layers. Inside the logp function, I will reshape the layers back to their original 3 dimensions:
        # num_layers x in_dim x out_dim, so we can perform the feed-forward step.
        hidden_layers = pm.Deterministic(f"{self.f_nn_weights_name}_hidden_reshaped", hidden_layers.reshape(
            (num_hidden_layers * hidden_layer_dim_in, hidden_layer_dim_out)))

        output_layer = pm.Normal(f"{self.f_nn_weights_name}_out",
                                 mu=self.parameters.weights_f.prior.mean,
                                 sigma=self.parameters.weights_f.prior.sd,
                                 size=(output_layer_dim_in, output_layer_dim_out),
                                 observed=observed_weights_f[2])

        # Because we cannot pass a string or a function to CustomDist, we will identify a function by a number and
        # we will retrieve its implementation in the feed-forward function.
        activation_function_number = ActivationFunction.NAME_TO_NUMBER[activation_function_name]

        return input_layer, hidden_layers, output_layer, activation_function_number

    def _create_random_symmetric_lag(self, lag: Any):
        if lag is None:
            # Use all mixture data to infer coordination
            symmetric_lag = np.zeros(self.num_subjects * (self.num_subjects - 1))
        else:
            # We create a matrix to generate symmetric values of the lags per pair. This is because when we shift
            # samples from the pair (a,b) by a lag l, we need to shift the samples of the pair (b,a) by a lag -l.
            lag_idx_per_pair = {}
            idx = 1
            for s1, s2 in itertools.combinations(range(self.num_subjects), 2):
                lag_idx_per_pair[f"{s2}#{s1}"] = idx
                lag_idx_per_pair[f"{s1}#{s2}"] = lag_idx_per_pair[f"{s2}#{s1}"] * -1
                idx += 1

            num_cols = self.num_subjects * (self.num_subjects - 1)
            num_rows = math.comb(self.num_subjects, 2)
            lag_symmetry_matrix = np.zeros((num_rows, num_cols), dtype=int)
            aux_idx = 0
            for s1 in range(self.num_subjects):
                for s2 in range(self.num_subjects):
                    if s1 == s2:
                        continue

                    # In the logp function, we have matrices that represent values of other subjects (s2) for each
                    # subject (s1). We want to be sure our lag variables match those matrices.
                    lag_idx = lag_idx_per_pair[f"{s2}#{s1}"]
                    lag_symmetry_matrix[abs(lag_idx) - 1, aux_idx] = 1 * np.sign(lag_idx)
                    aux_idx += 1

            # A symmetric lag will contain one lag per pair. For instance, consider a scenario with 3 subjects.
            # In this case we have the possible pairs: (1, 0), (2, 0), (0, 1), (2, 1), (0, 2), (1, 2) and lags:
            # l1, l2, -l1, l3, -l2, -l3.
            # l1 tells us by how much values from subject 1 need to be shifted to align with subject 0 (same
            # reasoning for the other lags)
            symmetric_lag = pm.Deterministic(f"{self.uuid}_symmetric_lag",
                                             ptt.clip(ptt.dot(lag, lag_symmetry_matrix), -self.max_lag,
                                                      self.max_lag))

        return symmetric_lag

    @staticmethod
    def _create_lag_mask(num_time_steps: int, lag: Any):
        # There should be one lag per pair of subjects. After we shift the samples applying the lags, we create a
        # mask to indicate the portion of the data that intersects. Coordination can only be inferred on that part.
        #
        # e.g.    Pair A: |-----------|             Pair A: |-----------| (-2 lag)
        #         Pair B: |-----------|  after lag  Pair B:       |-----------| (+4 lag)
        #         Pair C: |-----------|             Pair C:   |-----------|
        #                                                         |-----| = Intersection. We can only infer
        #                                                                   coordination on this part.
        #
        # The mask will be passed to the logp function to prevent gradient propagation in parts where coordination
        # should not interfere.

        if lag is None:
            lag_mask = np.ones((1, 1, num_time_steps))
        else:
            lower_idx = pm.math.maximum(0, ptt.max(lag))
            upper_idx = num_time_steps + pm.math.minimum(0, ptt.min(lag))  # Index not included.

            lag_mask = ptt.zeros((1, 1, num_time_steps))
            lag_mask = ptt.set_subtensor(lag_mask[..., lower_idx:upper_idx], 1)

        return lag_mask

    def update_pymc_model(self, coordination: Any, subject_dimension: str, feature_dimension: str, time_dimension: str,
                          observed_values: Optional[Any] = None, mean_a0: Optional[Any] = None,
                          sd_aa: Optional[Any] = None, mixture_weights: Optional[Any] = None,
                          num_hidden_layers_f: int = 0, activation_function_name_f: str = "linear",
                          dim_hidden_layer_f: int = 0, lag: Optional[Any] = None) -> Any:

        mean_a0, sd_aa, mixture_weights = self._create_random_parameters(mean_a0, sd_aa, mixture_weights)

        if num_hidden_layers_f > 0:
            input_layer_f, hidden_layers_f, output_layer_f, activation_function_number_f = self._create_random_weights_f(
                num_hidden_layers=num_hidden_layers_f, dim_hidden_layer=dim_hidden_layer_f,
                activation_function_name=activation_function_name_f)
        else:
            input_layer_f = []
            hidden_layers_f = []
            output_layer_f = []
            activation_function_number_f = 0

        # Auxiliary matrices to compute logp in a vectorized manner without having to loop over the individuals.
        expander_aux_mask_matrix = []
        aggregator_aux_mask_matrix = []
        for subject in range(self.num_subjects):
            expander_aux_mask_matrix.append(np.delete(np.eye(self.num_subjects), subject, axis=0))
            aux = np.zeros((self.num_subjects, self.num_subjects - 1))
            aux[subject] = 1
            aux = aux * mixture_weights[subject][None, :]
            aggregator_aux_mask_matrix.append(aux)

        expander_aux_mask_matrix = np.concatenate(expander_aux_mask_matrix, axis=0)
        aggregator_aux_mask_matrix = ptt.concatenate(aggregator_aux_mask_matrix, axis=1)

        symmetric_lag = self._create_random_symmetric_lag(lag)
        lag_mask = MixtureComponent._create_lag_mask(coordination.shape[-1].eval(), lag)

        if self.self_dependent:
            logp_params = (mean_a0,
                           sd_aa,
                           mixture_weights,
                           coordination,
                           symmetric_lag,
                           input_layer_f,
                           hidden_layers_f,
                           output_layer_f,
                           activation_function_number_f,
                           expander_aux_mask_matrix,
                           aggregator_aux_mask_matrix,
                           lag_mask)
            random_fn = partial(mixture_random_with_self_dependency,
                                num_subjects=self.num_subjects, dim_value=self.dim_value)
            mixture_component = pm.CustomDist(self.uuid, *logp_params, logp=mixture_logp_with_self_dependency,
                                              random=random_fn,
                                              dims=[subject_dimension, feature_dimension, time_dimension],
                                              observed=observed_values)
        else:
            logp_params = (mean_a0,
                           sd_aa,
                           mixture_weights,
                           coordination,
                           symmetric_lag,
                           input_layer_f,
                           hidden_layers_f,
                           output_layer_f,
                           activation_function_number_f,
                           expander_aux_mask_matrix,
                           aggregator_aux_mask_matrix,
                           lag_mask)

            random_fn = partial(mixture_random_without_self_dependency,
                                num_subjects=self.num_subjects, dim_value=self.dim_value)
            mixture_component = pm.CustomDist(self.uuid, *logp_params, logp=mixture_logp_without_self_dependency,
                                              random=random_fn,
                                              dims=[subject_dimension, feature_dimension, time_dimension],
                                              observed=observed_values)

        return mixture_component, mean_a0, sd_aa, mixture_weights
