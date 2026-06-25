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

from datetime import datetime
from datetime import timedelta
import logging
import os
import paramiko
import unittest

LOG = logging.getLogger(__name__)


class TestSELinuxKollaDenials(unittest.TestCase):
    """Do SELinux denials exist for kolla_ services within time window?"""

    @classmethod
    def setUpClass(cls):
        """Setup test environment and configuration.

        Read configuration from kolla-ansible environment variables.
        """

        cls.enabled = os.environ.get('SELINUX_TEST_ENABLED',
                                     'true').lower() == 'true'
        cls.time_window_minutes = int(os.environ.get(
            'SELINUX_TIME_WINDOW_MINUTES', 5))
        cls.target_host = os.environ.get('SELINUX_TARGET_HOST', 'localhost')
        cls.ssh_user = os.environ.get('SELINUX_SSH_USER', 'root')
        cls.ssh_private_key = os.environ.get(
            'SELINUX_SSH_PRIVATE_KEY', os.path.expanduser('~/.ssh/id_rsa'))
        cls.ssh_timeout = int(os.environ.get('SELINUX_SSH_TIMEOUT', 30))

        if not cls.enabled:
            raise unittest.SkipTest("SELinux tests are disabled")

        # Test SSH connection and SELinux status once for all tests
        cls.ssh = None
        try:
            cls.ssh = cls._get_ssh_connection()
            cls.selinux_status = cls._check_selinux_status(cls.ssh)
            if cls.selinux_status not in ["enforcing", "permissive"]:
                raise unittest.SkipTest(
                    f"SELinux is {cls.selinux_status}, skipping test")
        except Exception as e:
            if cls.ssh:
                cls.ssh.close()
            raise unittest.SkipTest(
                f"Cannot access host for SELinux check: {e}")

    @classmethod
    def tearDownClass(cls):
        """Clean up SSH connection after all tests."""

        if cls.ssh:
            cls.ssh.close()

    @classmethod
    def _get_ssh_connection(cls):
        """Establish SSH connection to target host."""

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())  # nosec B507

        try:
            ssh.connect(
                hostname=cls.target_host,
                username=cls.ssh_user,
                key_filename=cls.ssh_private_key,
                timeout=cls.ssh_timeout
            )
            return ssh
        except Exception as e:
            raise Exception(f"SSH connection failed: {e}")

    @classmethod
    def _check_selinux_status(cls, ssh):
        """Check if SELinux is enabled and return its status."""

        stdin, stdout, stderr = ssh.exec_command("getenforce")  # nosec B601
        status = stdout.read().decode('utf-8').strip().lower()
        return status

    def _get_time_window_string(self, minutes_ago):
        """Generate ausearch date and time strings for X minutes ago.

        Args:
            minutes_ago (int): Number of minutes to look back

        Returns:
            tuple: (date, time) strings suitable for ausearch -ts
        """

        target_time = datetime.now() - timedelta(minutes=minutes_ago)
        return (target_time.strftime("%x"),
                target_time.strftime("%H:%M:%S"))

    def _query_audit_logs(self, ssh, minutes_ago=None):
        """Query audit logs for AVC denials within configured time window.

        Args:
            ssh: SSH connection object
            minutes_ago (int): Override for time window (optional)

        Returns:
            list: Matching denial entries
        """

        if minutes_ago is None:
            minutes_ago = self.time_window_minutes

        if minutes_ago <= 0:
            self.fail(f"""Invalid time_window_minutes:
                      {minutes_ago} (must be > 0)""")

        start_date, start_time = self._get_time_window_string(minutes_ago)
        LOG.info(f"""Querying audit logs
                 from {start_date} {start_time} (last {minutes_ago}
                 minutes)""")

        # Build the ausearch command. ausearch -ts takes the date and time as
        # two separate arguments.
        command = f"sudo ausearch -m avc -ts {start_date} {start_time} -i"
        LOG.debug(f"Executing: {command}")

        try:
            stdin, stdout, stderr = ssh.exec_command(command)  # nosec B601
            # Close stdin to signal EOF. ausearch blocks reading stdin
            # until EOF over an SSH channel without a TTY.
            stdin.close()
            output = stdout.read().decode('utf-8')
            error = stderr.read().decode('utf-8')

            # ausearch returns non-zero if no matches or error
            if error:
                if "no matches" in error.lower():
                    LOG.info("No AVC denials found in time window")
                    return []
                else:
                    self.fail(f"ausearch error: {error}")

            # Filter for AVC denials whose source context is a kolla_ domain.
            denials = []
            for line in output.splitlines():
                if "kolla_" in line and (
                    "scontext=" in line or "svc=" in line
                ):
                    denials.append(line.strip())

            if denials:
                LOG.warning(f"Found {len(denials)} kolla_ denials")

            return denials

        except Exception as e:
            self.fail(f"Failed to query audit logs: {str(e)}")

    def test_no_kolla_svc_denials(self):
        """Main test: Any svc denials for kolla_ domain in time window?"""

        # Query audit logs with configured time window
        denials = self._query_audit_logs(self.ssh)

        # Fail if any denials found
        if denials:
            denial_details = "\n".join(denials)
            self.fail(f"""SELinux: Found {len(denials)}
                svc kolla_ domain denials in the last
                {self.time_window_minutes} minutes:\n"
                {denial_details}""")
        else:
            LOG.info(f"""SELinux: No svc denials for kolla_ domain
                found in last {self.time_window_minutes} minutes""")

    def test_no_kolla_svc_denials_specific_time(self):
        """Alternative test with custom 60-minute time window.

        Test with a specific time window (e.g., last 60 minutes)
        """

        custom_minutes = 60
        denials = self._query_audit_logs(self.ssh, custom_minutes)

        if denials:
            denial_details = "\n".join(denials)
            self.fail(f"""SELinux: Found {len(denials)} svc denials
                for kolla_ domain in the last
                {custom_minutes} minutes:\n{denial_details}""")

    def test_selinux_status(self):
        """Verify SELinux status is properly set."""

        self.assertIn(self.selinux_status, ["enforcing", "permissive"],
                      f"SELinux: SELinux status is {self.selinux_status},"
                      f"expected enforcing or permissive"
                      )
