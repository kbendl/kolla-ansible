#!/usr/bin/env python

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import copy
from importlib.machinery import SourceFileLoader
import os
import sys
from unittest import mock

from oslotest import base

sys.modules['dbus'] = mock.MagicMock()

this_dir = os.path.dirname(sys.modules[__name__].__file__)
ansible_dir = os.path.join(this_dir, '..', '..', 'ansible')
docker_worker_file = os.path.join(ansible_dir,
                                  'module_utils', 'kolla_docker_worker.py')
podman_worker_file = os.path.join(ansible_dir,
                                  'module_utils', 'kolla_podman_worker.py')

dwm = SourceFileLoader('kolla_docker_worker', docker_worker_file).load_module()
pwm = SourceFileLoader('kolla_podman_worker', podman_worker_file).load_module()


FAKE_DATA = {
    'params': {
        'container_engine': 'docker',
        'api_version': None,
        'auth_username': None,
        'auth_password': None,  # nosec B105
        'auth_registry': None,
        'auth_email': None,
        'restart_policy': 'unless-stopped',
        'restart_retries': 10,
        'graceful_timeout': 10,
        'client_timeout': 120,
        'command': None,
        'detach': True,
        'environment': {},
        'host_config': {
            'network_mode': 'host',
            'ipc_mode': '',
            'cap_add': None,
            'security_opt': None,
            'pid_mode': '',
            'privileged': False,
            'tmpfs': None,
            'volumes_from': None,
            'restart_policy': 'unless-stopped',
            'restart_retries': 10,
        },
        'labels': {
            'build-date': '2016-06-02',
            'kolla_version': '2.0.1',
            'license': 'GPLv2',
            'name': 'ubuntu Base Image',
            'vendor': 'ubuntuOS',
        },
        'image': 'myregistrydomain.com:5000/ubuntu:16.04',
        'name': 'test_container',
        'remove_on_exit': True,
        'volumes': None,
        'tty': False,
        'ipc_mode': None,
        'pid_mode': None,
        'privileged': False,
        'security_opt': None,
        'cap_add': [],
    },

    'container_inspect': {
        'Config': {
            'Env': ['KOLLA_BASE_DISTRO=rocky'],
            'Hostname': 'controller-01',
            'Volumes': {'/var/lib/kolla/config_files/': {}},
            'Labels': {},
        },
        'HostConfig': {
            'SecurityOpt': ['label=type:kolla_test_container_t'],
            'Privileged': False,
            'IpcMode': '',
            'PidMode': '',
        },
        'Mounts': {},
        'NetworkSettings': {},
        'State': {},
    },
}


def get_DockerWorker(mod_param):
    module = mock.MagicMock()
    module.params = copy.deepcopy(mod_param)

    common_options_defaults = {
        'auth_email': None,
        'auth_password': None,  # nosec B105
        'auth_registry': None,
        'auth_username': None,
        'environment': None,
        'restart_policy': None,
        'restart_retries': 10,
        'api_version': 'auto',
        'graceful_timeout': 10,
        'client_timeout': 120,
        'container_engine': 'docker',
    }

    new_args = module.params.pop('common_options', dict()) or dict()
    env_module_environment = module.params.pop('environment', dict()) or dict()

    for k, v in module.params.items():
        if v is None:
            if k in common_options_defaults:
                if k not in new_args and common_options_defaults[k] is not None:
                    new_args[k] = common_options_defaults[k]
        else:
            new_args[k] = v

    env_module_common_options = new_args.pop('environment', dict())
    new_args['environment'] = env_module_common_options
    new_args['environment'].update(env_module_environment)

    if not new_args.get('pid_mode', False):
        new_args.pop('pid_mode', None)
    if not new_args.get('ipc_mode', False):
        new_args.pop('ipc_mode', None)

    module.params = new_args

    with mock.patch("docker.APIClient") as MockedDockerClientClass:
        MockedDockerClientClass.return_value._version = '1.40'
        dw = dwm.DockerWorker(module)
        dw.systemd = mock.MagicMock()
        return dw


def get_PodmanWorker(mod_param):
    module = mock.MagicMock()
    module.params = copy.deepcopy(mod_param)
    pw = pwm.PodmanWorker(module)
    pw.systemd = mock.MagicMock()
    pw.pc = mock.MagicMock()
    return pw


# ---------------------------------------------------------------------------
# DockerWorker - build_host_config security_opt
#
# build_host_config returns self.dc.create_host_config(...) which is a
# MagicMock. We inspect call_args to see what security_opt was passed.
# ---------------------------------------------------------------------------

class TestDockerWorkerSecurityOpt(base.BaseTestCase):

    def setUp(self):
        super(TestDockerWorkerSecurityOpt, self).setUp()
        self.fake_data = copy.deepcopy(FAKE_DATA)

    def _security_opt_kwarg(self, dw):
        """Return the security_opt value passed to dc.create_host_config."""
        dw.build_host_config(binds=[])
        return dw.dc.create_host_config.call_args.kwargs.get('security_opt')

    def test_generates_label_from_container_name(self):
        """No explicit security_opt: label derived from container name."""
        self.fake_data['params']['name'] = 'nova_api'
        self.fake_data['params']['security_opt'] = None
        self.dw = get_DockerWorker(self.fake_data['params'])
        self.assertEqual(self._security_opt_kwarg(self.dw),
                         ['label=type:kolla_nova_api_t'])

    def test_explicit_security_opt_preserved(self):
        """Explicit security_opt must not be overridden by default label."""
        self.fake_data['params']['name'] = 'nova_api'
        self.fake_data['params']['security_opt'] = ['label=disable']
        self.dw = get_DockerWorker(self.fake_data['params'])
        self.assertEqual(self._security_opt_kwarg(self.dw), ['label=disable'])

    def test_label_contains_container_name_not_service_name(self):
        """Label must use the exact container name, preserving underscores."""
        self.fake_data['params']['name'] = 'neutron_openvswitch_agent'
        self.fake_data['params']['security_opt'] = None
        self.dw = get_DockerWorker(self.fake_data['params'])
        self.assertIn('label=type:kolla_neutron_openvswitch_agent_t',
                      self._security_opt_kwarg(self.dw))

    def test_empty_list_security_opt_triggers_default_label(self):
        """Empty list is treated the same as None: default label is applied."""
        self.fake_data['params']['name'] = 'mariadb'
        self.fake_data['params']['security_opt'] = []
        self.dw = get_DockerWorker(self.fake_data['params'])
        self.assertEqual(self._security_opt_kwarg(self.dw),
                         ['label=type:kolla_mariadb_t'])


# ---------------------------------------------------------------------------
# PodmanWorker - prepare_container_args security_opt
# ---------------------------------------------------------------------------

class TestPodmanWorkerSecurityOpt(base.BaseTestCase):

    def setUp(self):
        super(TestPodmanWorkerSecurityOpt, self).setUp()
        self.fake_data = copy.deepcopy(FAKE_DATA)
        self.fake_data['params']['container_engine'] = 'podman'

    def test_generates_label_from_container_name(self):
        """No explicit security_opt: label derived from container name."""
        self.fake_data['params']['name'] = 'rabbitmq'
        self.fake_data['params']['security_opt'] = None
        self.pw = get_PodmanWorker(self.fake_data['params'])
        kwargs = self.pw.prepare_container_args()
        self.assertEqual(kwargs.get('security_opt'),
                         ['label=type:kolla_rabbitmq_t'])

    def test_explicit_security_opt_not_overridden(self):
        """Explicit security_opt must not be overridden by default label."""
        self.fake_data['params']['name'] = 'rabbitmq'
        self.fake_data['params']['security_opt'] = ['label=type:custom_t']
        self.pw = get_PodmanWorker(self.fake_data['params'])
        kwargs = self.pw.prepare_container_args()
        self.assertEqual(kwargs['security_opt'], ['label=type:custom_t'])

    def test_empty_list_security_opt_triggers_default_label(self):
        """Empty list is treated the same as None: default label is applied."""
        self.fake_data['params']['name'] = 'rabbitmq'
        self.fake_data['params']['security_opt'] = []
        self.pw = get_PodmanWorker(self.fake_data['params'])
        kwargs = self.pw.prepare_container_args()
        self.assertEqual(kwargs.get('security_opt'),
                         ['label=type:kolla_rabbitmq_t'])


# ---------------------------------------------------------------------------
# ContainerWorker - _effective_security_opt (base class logic)
# ---------------------------------------------------------------------------

class TestEffectiveSecurityOpt(base.BaseTestCase):

    def setUp(self):
        super(TestEffectiveSecurityOpt, self).setUp()
        self.fake_data = copy.deepcopy(FAKE_DATA)

    def test_generates_label_from_name(self):
        self.fake_data['params']['name'] = 'keystone'
        self.fake_data['params']['security_opt'] = None
        self.dw = get_DockerWorker(self.fake_data['params'])
        self.assertEqual(self.dw._effective_security_opt(),
                         ['label=type:kolla_keystone_t'])

    def test_returns_explicit_opt_unchanged(self):
        self.fake_data['params']['security_opt'] = ['label=type:custom_t']
        self.dw = get_DockerWorker(self.fake_data['params'])
        self.assertEqual(self.dw._effective_security_opt(),
                         ['label=type:custom_t'])

    def test_returns_empty_when_no_name_no_opt(self):
        self.fake_data['params']['name'] = None
        self.fake_data['params']['security_opt'] = None
        self.dw = get_DockerWorker(self.fake_data['params'])
        self.assertEqual(self.dw._effective_security_opt(), [])

    def test_none_security_opt_treated_as_unset(self):
        self.fake_data['params']['name'] = 'memcached'
        self.fake_data['params']['security_opt'] = None
        self.dw = get_DockerWorker(self.fake_data['params'])
        self.assertEqual(self.dw._effective_security_opt(),
                         ['label=type:kolla_memcached_t'])


# ---------------------------------------------------------------------------
# ContainerWorker - compare_security_opt
# ---------------------------------------------------------------------------

class TestCompareSecurityOpt(base.BaseTestCase):

    def setUp(self):
        super(TestCompareSecurityOpt, self).setUp()
        self.fake_data = copy.deepcopy(FAKE_DATA)

    def _get_worker(self, name='test_container', security_opt=None,
                    privileged=False, ipc_mode=None, pid_mode=None):
        self.fake_data['params'].update({
            'name': name,
            'security_opt': security_opt,
            'privileged': privileged,
            'ipc_mode': ipc_mode,
            'pid_mode': pid_mode,
        })
        return get_DockerWorker(self.fake_data['params'])

    def test_no_change_when_labels_match(self):
        dw = self._get_worker(name='test_container', security_opt=None)
        container_info = copy.deepcopy(FAKE_DATA['container_inspect'])
        self.assertIsNone(dw.compare_security_opt(container_info))

    def test_detects_changed_label(self):
        dw = self._get_worker(name='test_container', security_opt=None)
        container_info = copy.deepcopy(FAKE_DATA['container_inspect'])
        container_info['HostConfig']['SecurityOpt'] = [
            'label=type:kolla_old_t']
        self.assertTrue(dw.compare_security_opt(container_info))

    def test_skipped_when_privileged(self):
        """Privileged containers must never trigger a security_opt diff."""
        dw = self._get_worker(name='nova_compute', privileged=True)
        container_info = copy.deepcopy(FAKE_DATA['container_inspect'])
        container_info['HostConfig']['SecurityOpt'] = None
        self.assertFalse(dw.compare_security_opt(container_info))

    def test_skipped_when_host_ipc(self):
        dw = self._get_worker(name='nova_api', ipc_mode='host')
        container_info = copy.deepcopy(FAKE_DATA['container_inspect'])
        self.assertFalse(dw.compare_security_opt(container_info))

    def test_skipped_when_host_pid(self):
        dw = self._get_worker(name='nova_api', pid_mode='host')
        container_info = copy.deepcopy(FAKE_DATA['container_inspect'])
        self.assertFalse(dw.compare_security_opt(container_info))

    def test_handles_missing_host_config_key(self):
        """KeyError on absent HostConfig must not propagate."""
        dw = self._get_worker(name='memcached')
        self.assertIsNotNone(dw.compare_security_opt({}))

    def test_handles_none_host_config(self):
        """None HostConfig raises AttributeError

        because None.get() not caught by the existing
        KeyError/TypeError handlers in compare_security_opt."""
        dw = self._get_worker(name='memcached')
        self.assertRaises(AttributeError,
                          dw.compare_security_opt,
                          {'HostConfig': None})

    def test_no_change_when_label_matches_default(self):
        """Container with SecurityOpt matching the generated default"""
        dw = self._get_worker(name='test_container')
        container_info = copy.deepcopy(FAKE_DATA['container_inspect'])
        container_info['HostConfig']['SecurityOpt'] = \
            ['label=type:kolla_test_container_t']
        self.assertIsNone(dw.compare_security_opt(container_info))


# ---------------------------------------------------------------------------
# Cross-worker label format consistency
# ---------------------------------------------------------------------------

class TestLabelFormatConsistency(base.BaseTestCase):
    """Label format must be identical across Docker and Podman."""

    def setUp(self):
        super(TestLabelFormatConsistency, self).setUp()
        self.fake_data = copy.deepcopy(FAKE_DATA)

    def test_docker_build_host_config_and_effective_security_opt_agree(self):
        name = 'glance_api'
        self.fake_data['params'].update({'name': name, 'security_opt': None})
        dw = get_DockerWorker(self.fake_data['params'])
        dw.build_host_config(binds=[])
        host_config_label = dw.dc.create_host_config.call_args.kwargs.get(
            'security_opt')
        effective_label = dw._effective_security_opt()
        self.assertEqual(host_config_label, effective_label)

    def test_podman_and_docker_generate_same_label(self):
        name = 'glance_api'

        docker_data = copy.deepcopy(FAKE_DATA)
        docker_data['params'].update({'name': name, 'security_opt': None})
        dw = get_DockerWorker(docker_data['params'])
        dw.build_host_config(binds=[])
        docker_label = dw.dc.create_host_config.call_args.kwargs.get(
            'security_opt')

        podman_data = copy.deepcopy(FAKE_DATA)
        podman_data['params'].update({
            'name': name,
            'security_opt': None,
            'container_engine': 'podman',
        })
        pw = get_PodmanWorker(podman_data['params'])
        podman_label = pw.prepare_container_args().get('security_opt')

        self.assertEqual(docker_label, podman_label)


# ---------------------------------------------------------------------------
# ContainerWorker - test default fallback on containers to --privileged
# ---------------------------------------------------------------------------

class TestPrivilegedFallback(base.BaseTestCase):
    """When _selinux_enable is false, containers fall back to privileged."""

    def setUp(self):
        super(TestPrivilegedFallback, self).setUp()
        self.fake_data = copy.deepcopy(FAKE_DATA)

    def test_privileged_skips_security_opt_comparison(self):
        """compare_security_opt returns False when privileged is True."""
        self.fake_data['params'].update({
            'name': 'nova_compute',
            'privileged': True,
            'security_opt': None,
        })
        dw = get_DockerWorker(self.fake_data['params'])
        container_info = copy.deepcopy(FAKE_DATA['container_inspect'])
        container_info['HostConfig']['SecurityOpt'] = ['label=type:kolla_old_t']
        # privileged → comparison skipped, no diff
        self.assertFalse(dw.compare_security_opt(container_info))

    def test_privileged_false_allows_security_opt_comparison(self):
        """When not privileged, security_opt comparison works normally."""
        self.fake_data['params'].update({
            'name': 'nova_api',
            'privileged': False,
            'security_opt': None,
        })
        dw = get_DockerWorker(self.fake_data['params'])
        # Container has a different SELinux label → should detect diff
        container_info = copy.deepcopy(FAKE_DATA['container_inspect'])
        container_info['HostConfig']['SecurityOpt'] = ['label=type:kolla_old_t']
        self.assertTrue(dw.compare_security_opt(container_info))

    def test_build_host_config_sets_privileged_when_selinux_disabled(self):
        """When SELinux is disabled, privileged should be set by Ansible layer."""
        # This test validates that when privileged=True is passed,
        # build_host_config reflects it correctly.
        self.fake_data['params'].update({
            'name': 'nova_compute',
            'privileged': True,
            'security_opt': None,
        })
        dw = get_DockerWorker(self.fake_data['params'])
        dw.build_host_config(binds=[])
        kwargs = dw.dc.create_host_config.call_args.kwargs
        self.assertTrue(kwargs.get('privileged'))
