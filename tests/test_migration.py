from __future__ import print_function

import os
import shutil

import yaml
from couchdb_cluster_admin.doc_models import ShardAllocationDoc
from mock.mock import patch
from nose_parameterized import parameterized

from commcare_cloud.commands.migrations.config import CouchMigration
from commcare_cloud.commands.migrations.couchdb import generate_rsync_lists
from commcare_cloud.environment.main import get_environment

TEST_ENVIRONMENTS_DIR = os.path.join(os.path.dirname(__file__), 'migration_config')
PLANS_DIR = os.path.join(TEST_ENVIRONMENTS_DIR, 'plans')
TEST_PLANS = os.listdir(PLANS_DIR)

def tearDown():
    # delete generated files
    for plan_name in TEST_PLANS:
        migration = _get_migration(plan_name)
        shutil.rmtree(migration.rsync_files_path)


def get_shard_allocation_func(mock_shard_allocation):
    allocations_by_db = {
        allocation['_id']: ShardAllocationDoc.wrap(allocation)
        for allocation in mock_shard_allocation
    }

    def _mock_get_shard_allocation(config, db_name, create=False):
        return allocations_by_db[db_name]

    return _mock_get_shard_allocation


@parameterized(TEST_PLANS)
@patch('commcare_cloud.environment.paths.ENVIRONMENTS_DIR', TEST_ENVIRONMENTS_DIR)
def test_migration_plan(plan_name):
    migration = _get_migration(plan_name)
    assert not migration.separate_source_and_target
    with open(os.path.join(PLANS_DIR, plan_name, 'expected_couch_config.yml')) as f:
        expected_couch_config_json = yaml.load(f)

    assert expected_couch_config_json == migration.target_couch_config.to_json()

    with open(os.path.join(PLANS_DIR, plan_name, 'mock_shard_allocation.yml')) as f:
        mock_shard_allocation = yaml.load(f)

    mock_func = get_shard_allocation_func(mock_shard_allocation)
    with patch('couchdb_cluster_admin.file_plan.get_shard_allocation', mock_func):
        files_by_host = generate_rsync_lists(migration)

    with open(os.path.join(PLANS_DIR, plan_name, 'expected_rsync_file.txt')) as exp:
        expected = exp.read()

    for host, file_path in files_by_host.items():
        source_ip = file_path.split('/')[-1].split('__')[0]
        assert '10.247.164.12' == source_ip
        with open(file_path, 'r') as f:
            actual = f.read()
        assert expected == actual, "file lists mismatch:\n\nExpected\n{}\nActual\n{}".format(expected, actual)


def _get_migration(plan_name):
    plan_path = os.path.join(PLANS_DIR, plan_name, 'plan.yml')
    migration = CouchMigration(get_environment('env1'), plan_path)
    return migration
