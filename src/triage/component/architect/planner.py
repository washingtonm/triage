import copy
import itertools
import logging

from triage.component import metta

from . import utils, state_table_generators


class Planner(object):

    def __init__(
        self,
        feature_start_time,
        label_names,
        label_types,
        states,
        matrix_directory,
        user_metadata,
        cohort_name='default',
    ):
        self.feature_start_time = feature_start_time  # earliest time included in features
        self.label_names = label_names
        self.label_types = label_types
        self.cohort_name = cohort_name
        self.states = states or [state_table_generators.DEFAULT_ACTIVE_STATE]
        self.matrix_directory = matrix_directory
        self.user_metadata = user_metadata

    def _generate_build_task(
        self,
        matrix_metadata,
        matrix_uuid,
        train_matrix,
        feature_dictionary
    ):
        return {
            'as_of_times': train_matrix['as_of_times'],
            'label_name': matrix_metadata['label_name'],
            'label_type': matrix_metadata['label_type'],
            'feature_dictionary': feature_dictionary,
            'matrix_directory': self.matrix_directory,
            'matrix_uuid': matrix_uuid,
            'matrix_metadata': matrix_metadata,
            'matrix_type': matrix_metadata['matrix_type']
        }

    def _make_metadata(self, matrix_definition, feature_dictionary, label_name,
                       label_type, state, matrix_type):
        """ Generate dictionary of matrix metadata.

        :param matrix_definition: temporal definition of matrix
        :param feature dictionary: feature tables and the columns within them to use as features
        :param label_name: name of label column
        :param label_type: type of label
        :param state: the entity state to be included in the matrix
        :param matrix_type: type (train/test) of matrix
        :type matrix_definition: dict
        :type feature dictionary: dict
        :type label_name: str
        :type label_type: str
        :type state: str
        :type matrix_type: str

        :return: metadata needed for matrix identification and modeling
        :rtype: dict
        """

        # make a human-readable label for this matrix
        matrix_id = '_'.join([
            label_name,
            label_type,
            str(matrix_definition['first_as_of_time']),
            str(matrix_definition['matrix_info_end_time'])
        ])
        matrix_metadata = {

            # temporal information
            'feature_start_time': self.feature_start_time,
            'end_time': matrix_definition['matrix_info_end_time'],
            'as_of_date_frequency': matrix_definition.get(
                'training_as_of_date_frequency',
                matrix_definition.get('test_as_of_date_frequency')
            ),

            # columns
            'indices': ['entity_id', 'as_of_date'],
            'feature_names': utils.feature_list(feature_dictionary),
            'feature_groups': feature_dictionary.names,
            'label_name': label_name,

            # other information
            'label_type': label_type,
            'label_timespan': matrix_definition.get(
                'test_label_timespan',
                matrix_definition.get('training_label_timespan', '0 days')
            ),
            'cohort_name': self.cohort_name,
            'state': state,
            'matrix_id': matrix_id,
            'matrix_type': matrix_type

        }
        matrix_metadata.update(matrix_definition)
        matrix_metadata.update(self.user_metadata)

        return(matrix_metadata)

    def generate_plans(self, matrix_set_definitions, feature_dictionaries):
        """Create build tasks and update the matrix definitions with UUIDs

        :param matrix_set_definitions: the temporal information needed to generate each matrix
        :param feature_dictionaries: combinations of features to include in matrices
        :type matrix_set_definitions: list
        :type feature_dictionaries: list

        :return: matrix set definitions (updated with matrix uuids) and build tasks
        :rtype: tuple (list, dict)
        """
        updated_definitions = []
        build_tasks = dict()
        for matrix_set in matrix_set_definitions:
            logging.info('Making plans for matrix set %s', matrix_set)
            logging.info(
                'Iterating over %s label names, %s label_types, %s states, '
                '%s feature dictionaries',
                len(self.label_names),
                len(self.label_types),
                len(self.states),
                len(feature_dictionaries)
            )
            train_matrix = matrix_set['train_matrix']
            for (
                label_name,
                label_type,
                state,
                feature_dictionary,
            ) in itertools.product(
                self.label_names,
                self.label_types,
                self.states,
                feature_dictionaries
            ):
                matrix_set_clone = copy.deepcopy(matrix_set)
                # get a uuid
                train_metadata = self._make_metadata(
                    train_matrix,
                    feature_dictionary,
                    label_name,
                    label_type,
                    state,
                    'train',
                )
                train_uuid = metta.generate_uuid(train_metadata)
                logging.info('Matrix UUID %s found for train metadata %s',
                             train_uuid, train_metadata)
                if train_uuid not in build_tasks:
                    build_tasks[train_uuid] = self._generate_build_task(
                        train_metadata,
                        train_uuid,
                        train_matrix,
                        feature_dictionary
                    )
                    logging.info('Train uuid %s not found in build tasks yet, '
                                 'so added', train_uuid)
                else:
                    logging.info('Train uuid %s already found in build tasks', train_uuid)
                matrix_set_clone['train_uuid'] = train_uuid

                test_uuids = []
                for test_matrix in matrix_set_clone['test_matrices']:
                    test_metadata = self._make_metadata(
                        test_matrix,
                        feature_dictionary,
                        label_name,
                        label_type,
                        state,
                        'test',
                    )
                    test_uuid = metta.generate_uuid(test_metadata)
                    logging.info('Matrix UUID %s found for test metadata %s',
                                 test_uuid, test_metadata)
                    if test_uuid not in build_tasks:
                        build_tasks[test_uuid] = self._generate_build_task(
                            test_metadata,
                            test_uuid,
                            test_matrix,
                            feature_dictionary
                        )
                        logging.info('Test uuid %s not found in build tasks '
                                     'yet, so added', test_uuid)
                    else:
                        logging.info('Test uuid %s already found in build tasks',
                                     test_uuid)

                    test_uuids.append(test_uuid)
                matrix_set_clone['test_uuids'] = test_uuids
                updated_definitions.append(matrix_set_clone)

        logging.info(
            'Planner is finished generating matrix plans. '
            '%s matrix definitions and %s unique build tasks found',
            len(updated_definitions),
            len(build_tasks.keys())
        )
        return updated_definitions, build_tasks
