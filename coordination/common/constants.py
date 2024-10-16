DEFAULT_SEED = 0
DEFAULT_NUM_TIME_STEPS = 100
DEFAULT_SUBJECT_NAMES = ["S1", "S2", "S3"]
DEFAULT_NUM_SUBJECTS = len(DEFAULT_SUBJECT_NAMES)
DEFAULT_NUM_SAMPLED_SERIES = 1
DEFAULT_BURN_IN = 2000
DEFAULT_NUM_SAMPLES = 2000
DEFAULT_NUM_CHAINS = 4
DEFAULT_NUM_JOBS_PER_INFERENCE = DEFAULT_NUM_CHAINS
DEFAULT_NUM_INFERENCE_JOBS = 1
DEFAULT_NUTS_INIT_METHOD = "jitter+adapt_diag"
DEFAULT_TARGET_ACCEPT = 0.9
DEFAULT_PROGRESS_SAVING_FREQUENCY = 100
DEFAULT_NUM_TIME_POINTS_FOR_PPA = 10
DEFAULT_PPA_WINDOW = 5
MAX_NUM_INFERENCE_RETRIES = 5
MIN_WAIT_TIME_BEFORE_INFERENCE_RETRY = (
    5  # We will sample a number randomly in the min max range.
)
MAX_WAIT_TIME_BEFORE_INFERENCE_RETRY = 10
