# Copyright (c) 2017 SUSE LLC, Inc. All Rights Reserved.
#
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
#
# http://pubs.vmware.com/vsphere-55/topic/com.vmware.wssdk.apiref.doc/right-pane.html

"""
Kubernetes Worker module implementation.
"""

from __future__ import print_function, absolute_import, division
import logging
import tempfile
import os
import base64
import re
import errno
from gatherer.modules import WorkerInterface
from collections import OrderedDict

try:
    import kubernetes  # pylint: disable=import-self
    import kubernetes.client
    from kubernetes.client.rest import ApiException
    from urllib3.exceptions import HTTPError
    HAS_REQUIRED_MODULES = True
except ImportError as ex:
    HAS_REQUIRED_MODULES = False


class Kubernetes(WorkerInterface):
    """
    Worker class for the Kubernetes.
    """

    DEFAULT_PARAMETERS = OrderedDict([
        ('url', ''),
        ('username', ''),
        ('password', ''),
        ('client-cert', ''),
        ('client-key', ''),
        ('ca-cert', ''),
        ('kubeconfig', ''),
        ('context', '')
    ])

    def __init__(self):
        """
        Constructor.

        :return:
        """

        self.log = logging.getLogger(__name__)
        self.url = self.user = self.password = None
        self.client_cert = self.client_key = self.ca_cert = None

    # pylint: disable=R0801
    def set_node(self, node):
        """
        Set node information

        :param node: Dictionary of the node description.
        :return: void
        """

        try:
            self._validate_parameters(node)
        except AttributeError as error:
            self.log.error(error)
            raise error

        self.url = node.get('url')
        self.user = node.get('username')
        self.password = node.get('password')
        self.client_cert = node.get('client-cert')
        self.client_key = node.get('client-key')
        self.ca_cert = node.get('ca-cert')
        self.kubeconfig = node.get('kubeconfig')
        self.context = node.get('context')

    def parameters(self):
        """
        Return default parameters

        :return: default parameter dictionary
        """

        return self.DEFAULT_PARAMETERS

    def run(self):
        """
        Start worker.

        :return: Dictionary of the hosts in the worker scope.
        """

        output = dict()
        self._setup_connection()
        try:
            api_instance = kubernetes.client.CoreV1Api()
            api_response = api_instance.list_node()

            for node in api_response.items:
                cpu = node.status.capacity.get('cpu')
                memory = 0
                reg = re.compile(r'^(\d+)(\w+)$')
                if reg.match(node.status.capacity.get('memory')):
                    memory, unit = reg.match(node.status.capacity.get('memory')).groups()
                    if unit == "Ki":
                        memory = int(memory) / 1024
                    if unit == "Gi":
                        memory = int(memory) * 1024
                arch = node.status.node_info.architecture
                if arch.lower() == "amd64":
                    arch = "x86_64"

                output[node.metadata.name] = {
                        'type': 'kubernetes',
                        'cpuArch': arch,
                        'cpuDescription': "(unknown)",
                        'cpuMhz': cpu,
                        'cpuVendor': "(unknown)",
                        'hostIdentifier': node.status.node_info.machine_id,
                        'name': node.metadata.name,
                        'os': node.status.node_info.os_image,
                        'osVersion': 1,
                        'ramMb': int(memory),
                        'totalCpuCores': cpu,
                        'totalCpuSockets': cpu,
                        'totalCpuThreads': 1,
                        'vms': {}
                        }

        except (ApiException, HTTPError) as exc:
            if isinstance(exc, ApiException) and exc.status == 404:
                self.log.error("API Endpoint not found (404)")
                output = None
            else:
                self.log.exception(
                    'Exception when calling CoreV1Api->list_node: {0}'.format(exc)
                )
                output = None

        finally:
            self._cleanup()
        return output

    def valid(self):
        """
        Check plugin class validity.

        :return: True if kubernetes module is installed.
        """

        return HAS_REQUIRED_MODULES

    def _setup_connection(self):
        """
        Setup and configure connection to Kubernetes
        """
        if self.kubeconfig and self.context:
            kubernetes.config.load_kube_config(config_file=self.kubeconfig, context=self.context)
        else:
            kubernetes.client.configuration.__init__()
            kubernetes.client.configuration.host = self.url
            kubernetes.client.configuration.user = self.user
            kubernetes.client.configuration.passwd = self.password
            if self.ca_cert:
                with tempfile.NamedTemporaryFile(prefix='kube-', delete=False) as cacert:
                    cacert.write(base64.b64decode(self.ca_cert))
                    kubernetes.client.configuration.ssl_ca_cert = cacert.name
            if self.client_cert:
                with tempfile.NamedTemporaryFile(prefix='kube-', delete=False) as cert:
                    cert.write(base64.b64decode(self.client_cert))
                    kubernetes.client.configuration.cert_file = cert.name
            if self.client_key:
                with tempfile.NamedTemporaryFile(prefix='kube-', delete=False) as key:
                    key.write(base64.b64decode(self.client_key))
                    kubernetes.client.configuration.key_file = key.name

    def _cleanup(self):
        """
        Remove temporary created files
        """

        for path in [kubernetes.client.configuration.ssl_ca_cert,
                     kubernetes.client.configuration.cert_file,
                     kubernetes.client.configuration.key_file]:
            Kubernetes._safe_rm(path)

    def _validate_parameters(self, node):
        """
        Validate parameters.

        :param node: Dictionary with the node description.
        :return:
        """

        if not node.get('url') and not (node.get('kubeconfig') and node.get('context')):
            raise AttributeError("Missing either parameter or value 'url' or 'kubeconfig' and 'context' in infile")

    @staticmethod
    def _safe_rm(path):
        """
        Safely remove a file. Do not raise any error. Just log possible problems
        """
        if path is None:
            path = ''
        if os.path.exists(path):  # Empty path returns to False
            try:
                os.remove(path)
            except (IOError, OSError) as ex:
                if ex.errno != errno.ENOENT:
                    log.error('Unable to remove file "{0}": {1}'.format(path, ex.message))
                pass
