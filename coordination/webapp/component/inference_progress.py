import time
import uuid
from typing import Any, Dict, List, Optional
import subprocess

import streamlit as st
from coordination.webapp.widget.drop_down import DropDownOption, DropDown
from coordination.webapp.entity.inference_run import InferenceRun
import os
from coordination.webapp.constants import INFERENCE_PARAMETERS_DIR, INFERENCE_TMP_DIR, \
    INFERENCE_RESULTS_DIR_STATE_KEY
from coordination.common.constants import (DEFAULT_BURN_IN, DEFAULT_NUM_CHAINS,
                                           DEFAULT_NUM_JOBS_PER_INFERENCE,
                                           DEFAULT_NUM_SAMPLES,
                                           DEFAULT_NUTS_INIT_METHOD,
                                           DEFAULT_SEED, DEFAULT_TARGET_ACCEPT,
                                           DEFAULT_NUM_INFERENCE_JOBS)
from copy import deepcopy
from coordination.model.config.mapper import DataMapper
from pkg_resources import resource_string
from coordination.model.builder import ModelBuilder
import json
import asyncio
from coordination.webapp.utils import get_inference_run_ids
from collections import OrderedDict
from coordination.webapp.component.inference_run_progress import InferenceRunProgress


class InferenceProgress:
    """
    Represents a component that displays a collection of inference runs and the progress of each
    one of them.
    """

    def __init__(self, component_key: str, inference_dir: str, refresh_rate: int):
        """
        Creates the component.

        @param component_key: unique identifier for the component in a page.
        @param inference_dir: directory where inference runs were saved.
        @param refresh_rate: how many seconds to wait before updating the progress.
        """
        self.component_key = component_key
        self.inference_dir = inference_dir
        self.refresh_rate = refresh_rate

    def create_component(self):
        """
        Creates area in the screen for selection of an inference run id. Below is presented a json
        object with the execution params of the run once one is chosen from the list.
        """
        asyncio.run(self._create_progress_area())

    async def _create_progress_area(self):
        """
        Populates the progress pane where one can see the progress of the different inference runs.

        WARNING:
        It's not possible to have widgets that require unique keys in this pane because the widget
        keys are not cleared until the next run. We could keep creating different keys but this
        would cause memory leakage as the keys would be accumulated in the run context.
        """
        progress_area = st.empty()
        while True:
            with progress_area:
                with st.container():
                    # The status contains a countdown showing how many seconds until the next
                    # refresh. It is properly filled in the end of this function after we parse
                    # all the experiments in the run and know how many of them have finished
                    # successfully.
                    status_text = st.empty()

                    run_ids = get_inference_run_ids(self.inference_dir)
                    if len(run_ids) <= 0:
                        await self._wait(status_text)
                        continue

                    for i, run_id in enumerate(run_ids):
                        inference_run = InferenceRun(
                            inference_dir=self.inference_dir,
                            run_id=run_id)

                        if not inference_run.execution_params:
                            continue

                        # Pre-expand just the first run in the list
                        with st.expander(run_id, expanded=(i == 0)):
                            inference_progress_component = InferenceRunProgress(inference_run)
                            inference_progress_component.create_component()

            await self._wait(status_text)

    async def _wait(self, countdown_area: st.container):
        """
        Waits a few seconds and update countdown.
        """
        for i in range(self.refresh_rate, 0, -1):
            countdown_area.write(f"**Refreshing in :red[{i} seconds].**")
            await asyncio.sleep(1)
