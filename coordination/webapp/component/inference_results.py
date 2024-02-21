from ast import literal_eval

import numpy as np
import pandas as pd
import streamlit as st

from coordination.inference.inference_run import InferenceRun
from coordination.inference.model_variable import ModelVariableInfo
from coordination.webapp.component.inference_stats import InferenceStats
from coordination.webapp.component.model_variable_inference_results import \
    ModelVariableInferenceResults
from coordination.webapp.constants import (DATA_DIR_STATE_KEY,
                                           DEFAULT_PLOT_MARGINS)
from coordination.webapp.utils import plot_series
from coordination.webapp.widget.drop_down import DropDown


class InferenceResults:
    """
    Represents a component that displays inference results for a model variable in an experiment
    from a particular inference run.
    """

    def __init__(
        self,
        component_key: str,
        inference_run: InferenceRun,
        experiment_id: str,
        model_variable_info: ModelVariableInfo,
        model_variable_dimension: str,
    ):
        """
        Creates the component.

        @param component_key: unique identifier for the component in a page.
        @param inference_run: object containing info about an inference run.
        @param experiment_id: experiment id from the inference run.
        @param model_variable_info: object containing info about the model variable.
        @param model_variable_dimension: dimension if the variable has more than one to choose
            from.
        """
        self.component_key = component_key
        self.inference_run = inference_run
        self.experiment_id = experiment_id
        self.model_variable_info = model_variable_info
        self.model_variable_dimension = model_variable_dimension

    def create_component(self):
        """
        Displays inference results in different forms depending on the variable selected.
        """
        if not self.experiment_id:
            return

        if not self.model_variable_info:
            return

        st.write(f"### {self.experiment_id}")

        sub_experiment_id = None
        if self.inference_run.ppa:
            sub_experiment_id = DropDown(
                label="Sub-experiment ID",
                key=f"{self.component_key}_sub_experiment_run_id_dropdown",
                options=self.inference_run.get_sub_experiment_ids(self.experiment_id),
            ).create()
            if sub_experiment_id:
                idata = self.inference_run.get_inference_data(
                    self.experiment_id, sub_experiment_id
                )
            else:
                return
        else:
            idata = self.inference_run.get_inference_data(self.experiment_id)

        if not idata:
            st.write(":red[No inference data found.]")
            return

        if self.model_variable_info.inference_mode == "inference_stats":
            convergence_report = InferenceResults._read_convergence_report(
                self.inference_run.inference_dir,
                self.inference_run.run_id,
                self.experiment_id,
                sub_experiment_id,
            )
            inference_stats_component = InferenceStats(
                component_key=f"{self.component_key}_inference_stats",
                inference_data=idata,
                convergence_report=convergence_report,
            )
            inference_stats_component.create_component()
        elif self.model_variable_info.inference_mode == "parameter_trace":
            # Add the matplotlib plot generated by a trace directly to the screen.
            st.pyplot(
                idata.plot_parameter_posterior(),
                clear_figure=True,
                use_container_width=True,
            )
        elif self.model_variable_info.inference_mode == "ppa":
            if self.inference_run.ppa:
                ppa_results = InferenceResults._get_ppa_results(
                    self.inference_run.inference_dir,
                    self.inference_run.run_id,
                    self.experiment_id,
                    sub_experiment_id,
                )
                st.write(ppa_results)
            else:
                st.write(":red[PPA not performed in this inference run.]")
        elif self.model_variable_info.inference_mode == "dataset":
            data = self.inference_run.data
            data = data[data["experiment_id"] == self.experiment_id].iloc[0]
            if pd.api.types.is_numeric_dtype(data[self.model_variable_dimension]):
                st.write(data[self.model_variable_dimension])
            else:
                curve = np.array(literal_eval(data[self.model_variable_dimension]))
                time_steps = np.arange(len(curve))
                fig = plot_series(x=time_steps, y=curve, marker=True)
                fig.update_layout(
                    xaxis_title="Time Step",
                    yaxis_title=self.model_variable_dimension,
                    # Preserve legend order
                    legend={"traceorder": "normal"},
                    margin=DEFAULT_PLOT_MARGINS,
                )

                st.plotly_chart(fig, use_container_width=True)

        else:
            model_variable_inference_results_component = ModelVariableInferenceResults(
                component_key=f"{self.component_key}_model_variable_inference_results",
                model_variable_info=self.model_variable_info,
                dimension=self.model_variable_dimension,
                inference_data=idata,
            )
            model_variable_inference_results_component.create_component()

    @staticmethod
    @st.cache_data
    def _read_convergence_report(
        inference_dir: str, run_id: str, experiment_id: str, sub_experiment_id: str
    ) -> pd.DataFrame:
        """
        Helper function to cache a convergence report. Generating a convergence report takes a
        while and we don't want to do it every time the page loads if we already loaded one before.

        @param inference_run: inference run object related to the convergence report.
        @param experiment_id: experiment id in the inference run for which to generate the report.
        @param sub_experiment_id: ID of a sub experiment.
        @return: convergence report.
        """
        inference_run = InferenceRun(
            inference_dir, run_id, data_dir=st.session_state[DATA_DIR_STATE_KEY]
        )
        idata = inference_run.get_inference_data(experiment_id, sub_experiment_id)
        return idata.generate_convergence_summary()

    @staticmethod
    @st.cache_data
    def _get_ppa_results(
        inference_dir: str, run_id: str, experiment_id: str, sub_experiment_id: str
    ) -> pd.DataFrame:
        """
        Helper function to cache a convergence report. Generating a convergence report takes a
        while and we don't want to do it every time the page loads if we already loaded one before.

        @param inference_run: inference run object related to the convergence report.
        @param experiment_id: experiment id in the inference run for which to generate the report.
        @param sub_experiment_id: ID of a sub experiment.
        @return: convergence report.
        """
        inference_run = InferenceRun(
            inference_dir, run_id, data_dir=st.session_state[DATA_DIR_STATE_KEY]
        )
        if not inference_run.ppa:
            return None

        model = inference_run.model
        if model is None:
            return ":red[**Could not construct the model.**]"

        idata = inference_run.get_inference_data(experiment_id, sub_experiment_id)
        data = inference_run.data
        row_df = data[data["experiment_id"] == experiment_id].iloc[0]

        # Populate config bundle with the data
        inference_run.data_mapper.update_config_bundle(model.config_bundle, row_df)

        summary_df = model.get_ppa_summary(
            idata=idata,
            window_size=inference_run.execution_params["ppa_window"],
            num_samples=100,
            seed=0,
        )

        return summary_df
