import matplotlib.pyplot as plt
import numpy as np
import time

import pandas as pd
from sklearn.metrics import mean_squared_error
from scipy.stats import pearsonr
from sklearn.model_selection import cross_validate, GridSearchCV

# Custom code
from coordination.common.dataset import EvidenceDataset, SeriesData, train_test_split, IndexToDatasetTransformer
from coordination.audio.audio import TrialAudio
from coordination.component.speech.vocalics_component import SegmentationMethod, VocalicsComponent
from coordination.entity.trial import Trial
from coordination.model.discrete_coordination import DiscreteCoordinationInferenceFromVocalics
from coordination.model.truncated_gaussian_coordination_blending import \
    TruncatedGaussianCoordinationBlendingInference
from coordination.model.logistic_coordination import LogisticCoordinationInferenceFromVocalics
from coordination.model.beta_coordination import BetaCoordinationInferenceFromVocalics
from coordination.model.gaussian_coordination_blending_latent_vocalics import \
    GaussianCoordinationBlendingInferenceLatentVocalics
from coordination.model.truncated_gaussian_coordination_blending_latent_vocalics import \
    TruncatedGaussianCoordinationBlendingInferenceLatentVocalics
from coordination.model.logistic_coordination_blending_latent_vocalics import \
    LogisticCoordinationBlendingInferenceLatentVocalics
from coordination.plot.coordination import add_discrete_coordination_bar
from coordination.report.coordination_change_report import CoordinationChangeReport
from sklearn.linear_model import BayesianRidge
from sklearn.pipeline import Pipeline
from coordination.model.coordination_transformer import CoordinationTransformer

from tqdm import tqdm


class CrossValidationHelper:

    def __init__(self, num_outer_splits: int, num_inner_splits: int, create_bars: bool = True):
        self.num_outer_splits = num_outer_splits
        self.num_inner_splits = num_inner_splits

        if create_bars:
            self.outer_pbar = tqdm(total=num_outer_splits, desc="Testing...", position=0)
            self.inner_pbar = tqdm(total=num_inner_splits, desc="Tuning...", position=1, leave=False)

        self.tuning_results = []

    def estimate_inner(self, estimator, X, y):
        """
        Estimates the MSE in the validation set. The inner cross validation splits the training into training and
        validation to perform hyperparameter tuning.
        """

        y_hat, _ = estimator.predict(X=X, return_std=True)
        mse = mean_squared_error(y, y_hat)

        self.inner_pbar.update()

        return mse

    def estimate_outer(self, estimator, X, y):
        pipe = estimator.best_estimator_
        y_hat, _ = pipe.predict(X=X, return_std=True)
        mse = mean_squared_error(y, y_hat)
        nll = pipe.steps[2][1].scores_[-1]

        if len(y) >= 2:
            r, p = pearsonr(pipe.steps[1][1].output_.flatten(), y_hat)
        else:
            r = 0
            p = -1

        self.tuning_results.append(estimator.cv_results_)
        # self.outer_pbar.update()

        return {
            "mse": mse,
            "pearson-r": r,
            "pearson-p": p,
            "nll": nll
        }

    def __copy__(self):
        cp = CrossValidationHelper(self.num_outer_splits, self.num_inner_splits, False)
        cp.outer_pbar = self.outer_pbar
        cp.inner_pbar = self.inner_pbar

        return cp

    def __deepcopy__(self, memo):
        cp = CrossValidationHelper(self.num_outer_splits, self.num_inner_splits, False)
        cp.outer_pbar = self.outer_pbar
        cp.inner_pbar = self.inner_pbar

        return cp


if __name__ == "__main__":
    # Constants
    NUM_TIME_STEPS = 17 * 60  # (17 minutes of mission in seconds)
    M = int(NUM_TIME_STEPS / 2)  # We assume coordination in the second half of the period is constant
    NUM_FEATURES = 2  # Pitch and Intensity

    # Common parameters
    MEAN_PRIOR_VOCALICS = np.zeros(NUM_FEATURES)
    STD_PRIOR_VOCALICS = np.ones(NUM_FEATURES)
    STD_COORDINATED_VOCALICS = np.ones(NUM_FEATURES)
    STD_OBSERVED_VOCALICS = np.ones(NUM_FEATURES) * 0.5
    ANTIPHASE_FUNCTION = lambda x, s: -x if s == 0 else x
    EITHER_PHASE_FUNCTION = lambda x, s: np.abs(x)

    # Parameters of the discrete model
    P_COORDINATION_TRANSITION = 0.1  # Coordination changes with small probability
    P_COORDINATION = 0  # The process starts with no coordination
    STD_UNCOORDINATED_VOCALICS = np.ones(NUM_FEATURES)

    # Parameters of the Gaussian model
    MEAN_COORDINATION_PRIOR = 0;
    STD_COORDINATION_PRIOR = 1E-16  # The process starts with no coordination
    STD_COORDINATION_DRIFT = 0.05  # Coordination drifts by a little

    # Parameters of the Beta model
    A0 = 1E-16
    B0 = 1E16  # The process starts with no coordination

    # model = DiscreteCoordinationInferenceFromVocalics(p_prior_coordination=P_COORDINATION,
    #                                                   p_coordination_transition=P_COORDINATION_TRANSITION,
    #                                                   mean_prior_vocalics=MEAN_PRIOR_VOCALICS,
    #                                                   std_prior_vocalics=STD_PRIOR_VOCALICS,
    #                                                   std_uncoordinated_vocalics=STD_UNCOORDINATED_VOCALICS,
    #                                                   std_coordinated_vocalics=STD_COORDINATED_VOCALICS)

    # fig = plt.figure(figsize=(8, 4))
    # plt.plot(x_test, func(x_test), color="blue", label="sin($2\\pi x$)")
    # plt.scatter(x_train, y_train, s=50, alpha=0.5, label="observation")
    # plt.plot(x_test, ymean, color="red", label="predict mean")
    # plt.fill_between(
    #     x_test, ymean - ystd, ymean + ystd, color="pink", alpha=0.5, label="predict std"
    # )

    # start = time.time()
    # params = inference_engine.predict(dataset)[0]
    # end = time.time()
    # print(f"Discrete: {end - start} seconds")
    # marginal_cs = params[0]
    # fig = plt.figure(figsize=(20, 6))
    # plt.plot(range(M + 1), marginal_cs, marker="o", color="tab:orange", linestyle="--")
    # plt.xlabel("Time Steps (seconds)")
    # plt.ylabel("Marginal Probability")
    # plt.title("Discrete Coordination Inference", fontsize=14, weight="bold")
    # times, masks = list(zip(*[(t, mask) for t, mask in enumerate(vocalic_series.mask) if mask > 0 and t <= M]))
    # plt.scatter(times, masks, color="tab:green", marker="+")
    # add_discrete_coordination_bar(main_ax=fig.gca(),
    #                               coordination_series=[np.where(marginal_cs > 0.5, 1, 0)],
    #                               coordination_colors=["tab:orange"],
    #                               labels=["Coordination"])
    # plt.show()
    #
    # inference_engine = TruncatedGaussianCoordinationBlendingInference(mean_prior_coordination=MEAN_COORDINATION_PRIOR,
    #                                                                   std_prior_coordination=STD_COORDINATION_PRIOR,
    #                                                                   std_coordination_drifting=STD_COORDINATION_DRIFT,
    #                                                                   mean_prior_vocalics=MEAN_PRIOR_VOCALICS,
    #                                                                   std_prior_vocalics=STD_PRIOR_VOCALICS,
    #                                                                   std_coordinated_vocalics=STD_COORDINATED_VOCALICS)
    # start = time.time()
    # params = inference_engine.predict(dataset)[0]
    # end = time.time()
    # print(f"Truncated Gaussian: {end - start} seconds")
    # mean_cs = params[0]
    # var_cs = params[1]
    # fig = plt.figure(figsize=(20, 6))
    # plt.plot(range(M + 1), mean_cs, marker="o", color="tab:orange", linestyle="--")
    # plt.fill_between(range(M + 1), mean_cs - np.sqrt(var_cs), mean_cs + np.sqrt(var_cs), color='tab:orange', alpha=0.2)
    # times, masks = list(zip(*[(t, mask) for t, mask in enumerate(vocalic_series.mask) if mask > 0 and t <= M]))
    # plt.scatter(times, masks, color="tab:green", marker="+")
    # plt.xlabel("Time Steps (seconds)")
    # plt.ylabel("Coordination")
    # plt.title("Continuous Coordination Inference", fontsize=14, weight="bold")
    # add_discrete_coordination_bar(main_ax=fig.gca(),
    #                               coordination_series=[np.where(mean_cs > 0.5, 1, 0)],
    #                               coordination_colors=["tab:orange"],
    #                               labels=["Coordination"])
    # plt.show()
    #

    #
    # start = time.time()
    # params = inference_engine.predict(dataset, num_particles=10000)[0]
    # end = time.time()
    # print(f"Gaussian Latent: {end - start} seconds")
    # mean_cs = params[0]
    # var_cs = params[1]
    # fig = plt.figure(figsize=(20, 6))
    # plt.plot(range(NUM_TIME_STEPS), mean_cs, marker="o", color="tab:orange", linestyle="--")
    # plt.fill_between(range(NUM_TIME_STEPS), np.clip(mean_cs - np.sqrt(var_cs), a_min=0, a_max=1),
    #                  np.clip(mean_cs + np.sqrt(var_cs), a_min=0, a_max=1), color='tab:orange', alpha=0.2)
    # times, masks = list(zip(*[(t, mask) for t, mask in enumerate(vocalic_series.mask) if mask > 0]))
    # plt.scatter(times, masks, color="tab:green", marker="+")
    # plt.xlabel("Time Steps (seconds)")
    # plt.ylabel("Coordination")
    # plt.title("Continuous Coordination Inference", fontsize=14, weight="bold")
    # add_discrete_coordination_bar(main_ax=fig.gca(),
    #                               coordination_series=[np.where(mean_cs > 0.5, 1, 0)],
    #                               coordination_colors=["tab:orange"],
    #                               labels=["Coordination"])
    # plt.show()
    #
    # np.random.seed(0)
    # model = TruncatedGaussianCoordinationBlendingInferenceLatentVocalics(
    #     mean_prior_coordination=MEAN_COORDINATION_PRIOR,
    #     std_prior_coordination=STD_COORDINATION_PRIOR,
    #     std_coordination_drifting=STD_COORDINATION_DRIFT,
    #     mean_prior_latent_vocalics=MEAN_PRIOR_VOCALICS,
    #     std_prior_latent_vocalics=STD_PRIOR_VOCALICS,
    #     std_coordinated_latent_vocalics=STD_COORDINATED_VOCALICS,
    #     std_observed_vocalics=STD_OBSERVED_VOCALICS,
    #     f=ANTIPHASE_FUNCTION,
    #     fix_coordination_on_second_half=False)
    #
    # start = time.time()
    # params = inference_engine.predict(dataset, num_particles=10000)[0]
    # end = time.time()
    # print(f"Truncated Gaussian Latent: {end - start} seconds")
    # mean_cs = params[0]
    # var_cs = params[1]
    # fig = plt.figure(figsize=(20, 6))
    # plt.plot(range(NUM_TIME_STEPS), mean_cs, marker="o", color="tab:orange", linestyle="--")
    # plt.fill_between(range(NUM_TIME_STEPS), np.clip(mean_cs - np.sqrt(var_cs), a_min=0, a_max=1),
    #                  np.clip(mean_cs + np.sqrt(var_cs), a_min=0, a_max=1), color='tab:orange', alpha=0.2)
    # times, masks = list(zip(*[(t, mask) for t, mask in enumerate(vocalic_series.mask) if mask > 0]))
    # plt.scatter(times, masks, color="tab:green", marker="+")
    # plt.xlabel("Time Steps (seconds)")
    # plt.ylabel("Coordination")
    # plt.title("Continuous Coordination Inference", fontsize=14, weight="bold")
    # add_discrete_coordination_bar(main_ax=fig.gca(),
    #                               coordination_series=[np.where(mean_cs > 0.5, 1, 0)],
    #                               coordination_colors=["tab:orange"],
    #                               labels=["Coordination"])
    # plt.show()
    #
    # np.random.seed(0)
    # model = LogisticCoordinationBlendingInferenceLatentVocalics(
    #     mean_prior_coordination=MEAN_COORDINATION_PRIOR,
    #     std_prior_coordination=STD_COORDINATION_PRIOR,
    #     std_coordination_drifting=STD_COORDINATION_DRIFT,
    #     mean_prior_latent_vocalics=MEAN_PRIOR_VOCALICS,
    #     std_prior_latent_vocalics=STD_PRIOR_VOCALICS,
    #     std_coordinated_latent_vocalics=STD_COORDINATED_VOCALICS,
    #     std_observed_vocalics=STD_OBSERVED_VOCALICS,
    #     f=ANTIPHASE_FUNCTION,
    #     fix_coordination_on_second_half=False)
    #
    # start = time.time()
    # params = inference_engine.predict(dataset, num_particles=10000)[0]
    # end = time.time()
    # print(f"Logistic Latent: {end - start} seconds")
    # mean_cs = params[0]
    # var_cs = params[1]
    # fig = plt.figure(figsize=(20, 6))
    # plt.plot(range(NUM_TIME_STEPS), mean_cs, marker="o", color="tab:orange", linestyle="--")
    # plt.fill_between(range(NUM_TIME_STEPS), np.clip(mean_cs - np.sqrt(var_cs), a_min=0, a_max=1),
    #                  np.clip(mean_cs + np.sqrt(var_cs), a_min=0, a_max=1), color='tab:orange', alpha=0.2)
    # times, masks = list(zip(*[(t, mask) for t, mask in enumerate(vocalic_series.mask) if mask > 0]))
    # plt.scatter(times, masks, color="tab:green", marker="+")
    # plt.xlabel("Time Steps (seconds)")
    # plt.ylabel("Coordination")
    # plt.title("Continuous Coordination Inference", fontsize=14, weight="bold")
    # add_discrete_coordination_bar(main_ax=fig.gca(),
    #                               coordination_series=[np.where(mean_cs > 0.5, 1, 0)],
    #                               coordination_colors=["tab:orange"],
    #                               labels=["Coordination"])
    # plt.show()

    # for outer in tqdm([10, 20, 30, 40, 50], desc=" outer", position=0):
    #     for inner in tqdm(range(outer), desc=" inner loop", position=1, leave=False):
    #         time.sleep(0.05)
    # print("done!")









    model = GaussianCoordinationBlendingInferenceLatentVocalics(
        mean_prior_coordination=MEAN_COORDINATION_PRIOR,
        std_prior_coordination=STD_COORDINATION_PRIOR,
        std_coordination_drifting=STD_COORDINATION_DRIFT,
        mean_prior_latent_vocalics=MEAN_PRIOR_VOCALICS,
        std_prior_latent_vocalics=STD_PRIOR_VOCALICS,
        std_coordinated_latent_vocalics=STD_COORDINATED_VOCALICS,
        std_observed_vocalics=STD_OBSERVED_VOCALICS,
        f=ANTIPHASE_FUNCTION,
        fix_coordination_on_second_half=False,
        num_particles=100,
        seed=0
    )

    series = []
    scores = []
    trials = ["T000671", "T000672", "T000719", "T000720", "T000725", "T000726", "T000739", "T000740"]
    for trial_number in trials:
        trial = Trial.from_directory(f"../data/study-3_2022/tomcat_agent/trials/{trial_number}/")
        vocalics_component = VocalicsComponent.from_vocalics(trial.vocalics,
                                                             segmentation_method=SegmentationMethod.KEEP_ALL)

        vocalic_series = vocalics_component.sparse_series(500, trial.metadata.mission_start)
        vocalic_series.normalize_per_subject()

        series.append(SeriesData(vocalic_series))
        scores.append(trial.metadata.team_score)

    dataset = EvidenceDataset(series, trials)

    print("Starting")

    model.configure_tensorboard("/Users/paulosoares/code/tomcat-coordination/data/tensorboard")
    reg = BayesianRidge(tol=1e-6, fit_intercept=False, compute_score=True)
    reg.set_params(alpha_init=1, lambda_init=1e-3)

    transformer = CoordinationTransformer(model)
    pipeline = Pipeline([
        ("coordination", transformer),
        ("score_regressor", reg),
    ])

    pipeline_cv = Pipeline([
        ("index_2_dataset", IndexToDatasetTransformer(dataset)),
        ("coordination", transformer),
        ("score_regressor", reg),
    ])

    helper = CrossValidationHelper(2, 8)

    np.random.seed(0)
    clf = GridSearchCV(estimator=pipeline_cv,
                       param_grid={"score_regressor__alpha_init": [1, 1e-3], "score_regressor__lambda_init": [1, 1e-3]},
                       cv=2,
                       scoring=helper.estimate_inner)

    start = time.time()
    final_result = cross_validate(
        estimator=clf,
        X=np.arange(dataset.num_trials)[:, np.newaxis],
        y=scores,
        cv=2,
        scoring=helper.estimate_outer,
        n_jobs=1
    )

    for result in helper.tuning_results:
        print(pd.DataFrame(result))

    print(pd.DataFrame(final_result))
    end = time.time()
    print(f"{(end - start)} seconds.")