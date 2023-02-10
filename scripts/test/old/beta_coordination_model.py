from typing import Optional

from copy import copy

import matplotlib.pyplot as plt
import numpy as np

from coordination.common.log import BaseLogger, TensorBoardLogger
from coordination.model.beta_coordination_blending_latent_vocalics import BetaCoordinationBlendingLatentVocalics
from coordination.model.utils.beta_coordination_blending_latent_vocalics import BetaCoordinationLatentVocalicsDataset, \
    BetaCoordinationLatentVocalicsTrainingHyperParameters

# Parameters
TIME_STEPS = 50
NUM_SAMPLES = 100
NUM_FEATURES = 2
DATA_TIME_SCALE_DENSITY = 1
P_SPEECH_SEMANTIC_LINK = 0
NUM_JOBS = 8

model_name = "beta_model"

VAR_UC = 0.25
VAR_CC = 0.01
VAR_A = 1
VAR_AA = 1
VAR_O = 1

SAMPLE_TO_INFER = 8
BURN_IN = 2000

train_hyper_parameters = BetaCoordinationLatentVocalicsTrainingHyperParameters(
    a_vu=1e-6,
    b_vu=1e-6,
    a_va=1e-6,
    b_va=1e-6,
    a_vaa=1e-6,
    b_vaa=1e-6,
    a_vo=1e-6,
    b_vo=1e-6,
    vu0=0.01,
    vc0=0.01,
    va0=1,
    vaa0=1,
    vo0=1,
    u_mcmc_iter=50,
    c_mcmc_iter=50,
    vu_mcmc_prop=0.001,
    vc_mcmc_prop=0.001
)


def estimate_parameters(model: BetaCoordinationBlendingLatentVocalics, evidence, burn_in: int, num_jobs: int,
                        logger: Optional[BaseLogger] = BaseLogger()):
    model.fit(evidence, train_hyper_parameters, burn_in=burn_in, seed=0, num_jobs=num_jobs, logger=logger)
    print(f"Estimated var_u / True var_uc = {model.parameters.var_u} / {VAR_UC}")
    print(f"Estimated var_c / True var_cc = {model.parameters.var_c} / {VAR_CC}")
    print(f"Estimated var_a / True var_a = {model.parameters.var_a} / {VAR_A}")
    print(f"Estimated var_aa / True var_aa = {model.parameters.var_aa} / {VAR_AA}")
    print(f"Estimated var_o / True var_o = {model.parameters.var_o} / {VAR_O}")


# For parallelism to work, the script has to be called in a __main__ section
if __name__ == "__main__":
    model = BetaCoordinationBlendingLatentVocalics(
        initial_coordination=0.2,
        num_vocalic_features=NUM_FEATURES,
        num_speakers=3
    )

    model.parameters.set_var_u(VAR_UC)
    model.parameters.set_var_c(VAR_CC)
    model.parameters.set_var_a(VAR_A)
    model.parameters.set_var_aa(VAR_AA)
    model.parameters.set_var_o(VAR_O)

    samples = model.sample(NUM_SAMPLES, TIME_STEPS, seed=0, time_scale_density=DATA_TIME_SCALE_DENSITY,
                           p_semantic_links=P_SPEECH_SEMANTIC_LINK)

    # # Plot the first unbounded coordination and coordination
    # # Plot estimated unbounded coordination against the real coordination points
    # plt.figure(figsize=(15, 8))
    # ts = np.arange(TIME_STEPS)
    # for i in range(10):
    #     plt.plot(ts, samples.unbounded_coordination[i], alpha=0.7, marker="o", label=f"Sample {i + 1}")
    # plt.title("1st 10 Unbounded Coordination Samples")
    # plt.legend()
    # plt.savefig(f"/Users/paulosoares/code/tomcat-coordination/boards/{model_name}/images/1st_10_uc_samples.png")
    # plt.show()
    #
    # # Plot estimated coordination against the real coordination points
    # plt.figure(figsize=(15, 8))
    # ts = np.arange(TIME_STEPS)
    # for i in range(10):
    #     plt.plot(ts, samples.coordination[i], alpha=0.7, marker="o", label=f"Sample {i + 1}")
    # plt.title("1st 10 Coordination Samples")
    # plt.legend()
    # plt.savefig(f"/Users/paulosoares/code/tomcat-coordination/boards/{model_name}/images/1st_10_c_samples.png")
    # plt.show()

    full_evidence = BetaCoordinationLatentVocalicsDataset.from_samples(samples)

    tmp = copy(samples)
    tmp.coordination = None
    tmp.latent_vocalics = None
    evidence_unbounded_coordination_only = BetaCoordinationLatentVocalicsDataset.from_samples(tmp)

    tmp = copy(samples)
    tmp.unbounded_coordination = None
    tmp.latent_vocalics = None
    evidence_coordination_only = BetaCoordinationLatentVocalicsDataset.from_samples(tmp)

    tmp = copy(samples)
    tmp.unbounded_coordination = None
    tmp.coordination = None
    evidence_latent_vocalics_only = BetaCoordinationLatentVocalicsDataset.from_samples(tmp)

    tmp = copy(samples)
    tmp.unbounded_coordination = None
    evidence_no_unbounded_coordination = BetaCoordinationLatentVocalicsDataset.from_samples(tmp)

    tmp = copy(samples)
    tmp.coordination = None
    evidence_no_coordination = BetaCoordinationLatentVocalicsDataset.from_samples(tmp)

    tmp = copy(samples)
    tmp.latent_vocalics = None
    evidence_no_latent_vocalics = BetaCoordinationLatentVocalicsDataset.from_samples(tmp)

    tmp = copy(samples)
    tmp.unbounded_coordination = None
    tmp.coordination = None
    tmp.latent_vocalics = None
    partial_evidence = BetaCoordinationLatentVocalicsDataset.from_samples(tmp)

    # Provide complete data to estimate the true model negative-loglikelihood
    model.fit(full_evidence, train_hyper_parameters, burn_in=0, seed=0, num_jobs=1)
    true_nll = model.nll_[-1]

    print(f"True NLL = {true_nll}")

    # Check if we can estimate the parameters from the complete data
    print()
    print("Parameter estimation with full evidence")
    model.reset_parameters()
    estimate_parameters(model=model, evidence=full_evidence, burn_in=1, num_jobs=1)
    #
    # # No Unbounded Coordination
    # print()
    # print("Parameter estimation NO unbounded coordination")
    # tb_logger = TensorBoardLogger(
    #     f"/Users/paulosoares/code/tomcat-coordination/boards/{model_name}/evidence_no_unbounded_coordination")
    # tb_logger.add_info("data_time_scale_density", DATA_TIME_SCALE_DENSITY)
    # model.reset_parameters()
    # estimate_parameters(model=model, evidence=evidence_no_unbounded_coordination, burn_in=BURN_IN, num_jobs=NUM_JOBS,
    #                     logger=tb_logger)
    #
    # # No Coordination
    # print()
    # print("Parameter estimation NO coordination")
    # tb_logger = TensorBoardLogger(
    #     f"/Users/paulosoares/code/tomcat-coordination/boards/{model_name}/evidence_no_coordination")
    # tb_logger.add_info("data_time_scale_density", DATA_TIME_SCALE_DENSITY)
    # model.reset_parameters()
    # estimate_parameters(model=model, evidence=evidence_no_coordination, burn_in=BURN_IN, num_jobs=NUM_JOBS,
    #                     logger=tb_logger)
    #
    # # No Latent Vocalics
    # print()
    # print("Parameter estimation NO latent vocalics")
    # tb_logger = TensorBoardLogger(
    #     f"/Users/paulosoares/code/tomcat-coordination/boards/{model_name}/evidence_no_latent_vocalics")
    # tb_logger.add_info("data_time_scale_density", DATA_TIME_SCALE_DENSITY)
    # model.reset_parameters()
    # estimate_parameters(model=model, evidence=evidence_no_latent_vocalics, burn_in=BURN_IN, num_jobs=NUM_JOBS,
    #                     logger=tb_logger)
    #
    # # With Unbounded Coordination only
    # print()
    # print("Parameter estimation with unbounded coordination only")
    # tb_logger = TensorBoardLogger(
    #     f"/Users/paulosoares/code/tomcat-coordination/boards/{model_name}/evidence_with_unbounded_coordination_only")
    # tb_logger.add_info("data_time_scale_density", DATA_TIME_SCALE_DENSITY)
    # model.reset_parameters()
    # estimate_parameters(model=model, evidence=evidence_unbounded_coordination_only, burn_in=BURN_IN, num_jobs=NUM_JOBS,
    #                     logger=tb_logger)
    #
    # # With Coordination only
    # print()
    # print("Parameter estimation with coordination only")
    # tb_logger = TensorBoardLogger(
    #     f"/Users/paulosoares/code/tomcat-coordination/boards/{model_name}/evidence_with_coordination_only")
    # tb_logger.add_info("data_time_scale_density", DATA_TIME_SCALE_DENSITY)
    # model.reset_parameters()
    # estimate_parameters(model=model, evidence=evidence_coordination_only, burn_in=BURN_IN, num_jobs=NUM_JOBS,
    #                     logger=tb_logger)
    #
    # # With Unbounded Latent Vocalics only
    # print()
    # print("Parameter estimation with latent vocalics only")
    # tb_logger = TensorBoardLogger(
    #     f"/Users/paulosoares/code/tomcat-coordination/boards/{model_name}/evidence_with_latent_vocalics_only")
    # tb_logger.add_info("data_time_scale_density", DATA_TIME_SCALE_DENSITY)
    # model.reset_parameters()
    # estimate_parameters(model=model, evidence=evidence_latent_vocalics_only, burn_in=BURN_IN, num_jobs=NUM_JOBS,
    #                     logger=tb_logger)

    # Check if we can estimate the parameters if we do not observe latent vocalics and coordination
    # print()
    # print("Parameter estimation with partial evidence")
    # tb_logger = TensorBoardLogger(f"/Users/paulosoares/code/tomcat-coordination/boards/{model_name}/partial_evidence")
    # tb_logger.add_info("data_time_scale_density", DATA_TIME_SCALE_DENSITY)
    # model.reset_parameters()
    # estimate_parameters(model=model, evidence=partial_evidence, burn_in=BURN_IN, num_jobs=NUM_JOBS, logger=tb_logger)

    # Check if we can predict coordination over time for the 1st sample
    model.var_uc = VAR_UC
    model.var_cc = VAR_CC
    model.var_a = VAR_A
    model.var_aa = VAR_AA
    model.var_o = VAR_O
    # summary = model.predict(evidence=partial_evidence.get_subset([SAMPLE_TO_INFER]), num_particles=30000, seed=0,
    #                         num_jobs=1)
    summary = model.predict(evidence=partial_evidence, num_particles=30000, seed=0,
                            num_jobs=1)
    #
    # # Plot estimated unbounded coordination against the real coordination points
    # plt.figure(figsize=(15, 8))
    # means = summary[0].unbounded_coordination_mean
    # stds = np.sqrt(summary[0].unbounded_coordination_var)
    # ts = np.arange(TIME_STEPS)
    # plt.plot(ts, means, color="tab:orange", marker="o")
    # plt.fill_between(ts, means - stds, means + stds, color="tab:orange", alpha=0.5)
    # plt.plot(ts, samples.unbounded_coordination[SAMPLE_TO_INFER], color="tab:blue", marker="o", alpha=0.5)
    # plt.title("Unbounded Coordination")
    # plt.show()
    #
    # Plot estimated coordination against the real coordination points
    plt.figure(figsize=(15, 8))
    # means = summary[0].coordination_mean
    # stds = np.sqrt(summary[0].coordination_var)
    means = np.array([s.coordination_mean for s in summary]).mean(axis=0)
    stds = np.sqrt(np.array([s.coordination_var for s in summary]).mean(axis=0))
    ts = np.arange(TIME_STEPS)
    plt.plot(ts, means, color="tab:orange", marker="o")
    plt.fill_between(ts, means - stds, means + stds, color="tab:orange", alpha=0.5)
    # plt.plot(ts, samples.coordination[SAMPLE_TO_INFER], color="tab:blue", marker="o", alpha=0.5)
    plt.plot(ts, samples.coordination.mean(axis=0), color="tab:blue", marker="o", alpha=0.5)

    # Semantic links
    semantic_link_times = [t for t, link in enumerate(full_evidence.speech_semantic_links[SAMPLE_TO_INFER]) if
                           link == 1]

    plt.scatter(semantic_link_times, np.ones(len(semantic_link_times)) * 1.1, marker="s", color="tab:purple")

    plt.title("Coordination")
    plt.show()
    #
    # plt.figure(figsize=(15, 8))
    # means = summary[0].coordination_mean
    # stds = np.sqrt(summary[0].coordination_var)
    # ts = np.arange(TIME_STEPS)
    # for i in range(NUM_FEATURES):
    #     plt.plot(ts, samples.latent_vocalics[SAMPLE_TO_INFER].values[i], marker="o", alpha=0.5,
    #              label=f"Feature {i + 1}")
    # plt.title("Latent Vocalics")
    # plt.legend()
    # plt.show()
    #
    # model.fit(full_evidence.get_subset([SAMPLE_TO_INFER]), burn_in=1, seed=0, num_jobs=1)
    # true_nll_1st_sample = model.nll_[-1]
    #
    # latent_vocalics = copy(samples.latent_vocalics[SAMPLE_TO_INFER])
    # latent_vocalics.values = summary[0].latent_vocalics_mean
    # estimated_dataset = BetaCoordinationLatentVocalicsDataset([
    #     BetaCoordinationLatentVocalicsDataSeries("0", samples.observed_vocalics[SAMPLE_TO_INFER],
    #                                              summary[0].unbounded_coordination_mean,
    #                                              summary[0].coordination_mean,
    #                                              latent_vocalics)])
    #
    # model.fit(estimated_dataset, burn_in=0, seed=0, num_jobs=1)
    # print(f"True NLL 1st Sample = {true_nll_1st_sample}")
    # print(f"Estimated NLL = {model.nll_[-1]}")