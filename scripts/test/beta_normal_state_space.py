import matplotlib.pyplot as plt
import numpy as np
from scipy.stats import beta, norm


def logit(x):
    return np.log(x / (1 - x))


def sigmoid(x):
    return np.exp(x) / (1 + np.exp(x))


if __name__ == "__main__":
    NUM_SAMPLES = 10000
    NUM_TIME_STEPS = 50

    THETA_0 = logit(0.3)
    THETA_STD = 0.05
    R_STD = 0.05
    C_STD = 0.01

    np.random.seed(0)

    thetas = []
    cs = []
    for t in range(NUM_TIME_STEPS):
        if t == 0:
            thetas.append(np.ones(NUM_SAMPLES) * THETA_0)
        else:
            thetas.append(norm(thetas[t - 1], THETA_STD).rvs())

        r = norm(np.zeros(NUM_SAMPLES), R_STD).rvs()

        m = sigmoid(thetas[t] + r)
        cs.append(beta(a=m / C_STD + m, b=(1 - m) * (1 - C_STD) / C_STD).rvs())

    thetas = np.array(thetas).T
    cs = np.array(cs).T

    plt.figure()
    plt.title("$\\theta_t$")
    plt.plot(range(NUM_TIME_STEPS), thetas.mean(axis=0), color="tab:blue", alpha=0.7, marker="o")
    plt.fill_between(range(NUM_TIME_STEPS), thetas.mean(axis=0) - thetas.std(axis=0),
                     thetas.mean(axis=0) + thetas.std(axis=0), color="tab:blue", alpha=0.7)
    plt.show()

    plt.figure()
    plt.title("Coordination")
    plt.plot(range(NUM_TIME_STEPS), cs.mean(axis=0), color="tab:orange", alpha=0.7, marker="o")
    plt.fill_between(range(NUM_TIME_STEPS), cs.mean(axis=0) - cs.std(axis=0),
                     cs.mean(axis=0) + cs.std(axis=0), color="tab:orange", alpha=0.7)
    plt.ylim([0, 1])
    plt.show()

    plt.figure()
    plt.title("Coordination Samples")
    for i in range(3):
        plt.plot(range(NUM_TIME_STEPS), cs[i], alpha=0.7, marker="o")
    plt.ylim([0, 1])
    plt.show()