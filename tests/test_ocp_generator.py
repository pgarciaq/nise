#
# Copyright 2020 Red Hat, Inc.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
"""OCP Generator Unit Tests."""

import random
from copy import copy
from datetime import datetime
from datetime import timedelta
from unittest import TestCase
from uuid import NAMESPACE_DNS
from uuid import uuid5
from unittest.mock import Mock
from unittest.mock import patch

from faker import Faker

from nise.generators.ocp.ocp_generator import GIGABYTE
from nise.generators.ocp.ocp_generator import GPU_MODELS
from nise.generators.ocp.ocp_generator import GPU_VENDOR
from nise.generators.ocp.ocp_generator import OCP_GPU_USAGE
from nise.generators.ocp.ocp_generator import OCP_GPU_USAGE_COLUMNS
from nise.generators.ocp.ocp_generator import OCP_NAMESPACE_LABEL
from nise.generators.ocp.ocp_generator import OCP_NODE_LABEL
from nise.generators.ocp.ocp_generator import OCP_NODE_LABEL_COLUMNS
from nise.generators.ocp.ocp_generator import OCP_POD_USAGE
from nise.generators.ocp.ocp_generator import OCP_POD_USAGE_COLUMNS
from nise.generators.ocp.ocp_generator import OCP_ROS_CLUSTER_QUOTA
from nise.generators.ocp.ocp_generator import OCP_ROS_CLUSTER_QUOTA_COLUMN
from nise.generators.ocp.ocp_generator import OCP_ROS_NAMESPACE_USAGE
from nise.generators.ocp.ocp_generator import OCP_ROS_NAMESPACE_USAGE_COLUMN
from nise.generators.ocp.ocp_generator import cluster_quota_hard_and_used_values
from nise.generators.ocp.ocp_generator import OCP_ROS_USAGE
from nise.generators.ocp.ocp_generator import OCP_ROS_USAGE_COLUMN
from nise.generators.ocp.ocp_generator import OCP_STORAGE_COLUMNS
from nise.generators.ocp.ocp_generator import OCP_STORAGE_USAGE
from nise.generators.ocp.ocp_generator import OCP_VM_USAGE
from nise.generators.ocp.ocp_generator import OCP_REPORT_TYPE_TO_COLS
from nise.generators.ocp.ocp_generator import COST_OCP_REPORT_TYPE_TO_COLS
from nise.generators.ocp.ocp_generator import ROS_OCP_REPORT_TYPE_TO_COLS
from nise.generators.ocp.ocp_generator import OCPGenerator
from nise.generators.ocp.ocp_generator import _gen_ros_gpu_metrics
from nise.generators.ocp.ocp_generator import machineset_name_from_node
from nise.generators.ocp.ocp_generator import node_capacity_pods_for_node

MAX_VOL_GIGS = 100


class OCPGeneratorTestCase(TestCase):
    """TestCase class for OCP Generator."""

    def setUp(self):
        """Test setup."""
        self.fake = Faker()
        self.now = datetime.now().replace(microsecond=0, second=0, minute=0)
        self.one_hour = timedelta(minutes=60)
        self.one_day = timedelta(hours=24)
        self.two_hours_ago = self.now - (2 * self.one_hour)

        self.attributes = {
            "nodes": [
                {
                    "node": self.fake.uuid4(),
                    "node_name": self.fake.word(),
                    "node_labels": (
                        f"label_{self.fake.word()}:{self.fake.word()}|label_{self.fake.word()}:{self.fake.word()}"
                    ),
                    "cpu_cores": self.fake.pyint(1, 10),
                    "memory_gig": self.fake.pyint(1, 32),
                    "namespaces": {
                        f"namespace_{self.fake.word()}": {
                            "pods": [
                                {
                                    "pod": self.fake.uuid4(),
                                    "pod_name": f"pod_{self.fake.word()}",
                                    "cpu_request": self.fake.pyint(1, 10),
                                    "mem_request_gig": self.fake.pyint(1, 32),
                                    "cpu_limit": self.fake.pyint(1, 10),
                                    "mem_limit_gig": self.fake.pyint(1, 32),
                                    "pod_seconds": self.fake.pyint(300, 3600),
                                    "cpu_usage": self._usage_dict(),
                                    "mem_usage_gig": self._usage_dict(),
                                    "labels": (
                                        f"label_{self.fake.word()}:{self.fake.word()}"
                                        f"|label_{self.fake.word()}:{self.fake.word()}"
                                    ),
                                },
                                {
                                    "pod": self.fake.uuid4(),
                                    "pod_name": f"pod_{self.fake.word()}",
                                    "cpu_request": self.fake.pyint(1, 10),
                                    "mem_request_gig": self.fake.pyint(1, 32),
                                    "cpu_limit": self.fake.pyint(1, 10),
                                    "mem_limit_gig": self.fake.pyint(1, 32),
                                    "labels": (
                                        f"label_{self.fake.word()}:{self.fake.word()}"
                                        f"|label_{self.fake.word()}:{self.fake.word()}"
                                    ),
                                },
                            ],
                            "volumes": [
                                {
                                    "volume_name": f"vol_{self.fake.word()}",
                                    "volume_request_gig": self.fake.pyint(50, MAX_VOL_GIGS),
                                    "volume_claims": [
                                        {
                                            "volume_claim_name": f"volumeclaim_{self.fake.word()}",
                                            "pod_name": f"pod_{self.fake.word()}",
                                            "capacity_gig": self.fake.pyint(1, 50),
                                            "volume_claim_usage_gig": self._usage_dict(),
                                            "labels": (
                                                f"label_{self.fake.word()}:{self.fake.word()}"
                                                f"|label_{self.fake.word()}:{self.fake.word()}"
                                            ),
                                        }
                                    ],
                                    "labels": (
                                        f"label_{self.fake.word()}:{self.fake.word()}"
                                        f"|label_{self.fake.word()}:{self.fake.word()}"
                                    ),
                                },
                                {
                                    "volume_name": f"vol_{self.fake.word()}",
                                    "volume_request_gig": self.fake.pyint(1, MAX_VOL_GIGS),
                                    "labels": (
                                        f"label_claimless:{self.fake.word()}"
                                        f"|label_{self.fake.word()}:{self.fake.word()}"
                                    ),
                                },
                            ],
                        }
                    },
                }
            ]
        }

    def _usage_dict(self):
        dikt = {}
        for _ in range(0, self.fake.pyint(3, 10)):
            day = self.fake.date_between_dates(self.now - (7 * self.one_day), self.now)
            dikt[day.strftime("%m-%d-%Y")] = self.fake.pyint(1, 10)
        return dikt

    def test_init_no_attributes(self):
        """Test the init without attributes."""
        generator = OCPGenerator(self.two_hours_ago, self.now, {})

        for attribute in ["nodes", "namespaces", "pods", "namespace2pods", "volumes"]:
            with self.subTest(attribute=attribute):
                attr = getattr(generator, attribute)
                self.assertIsNotNone(attr)

                if attribute in ("nodes", "volumes"):
                    self.assertIsInstance(attr, list)
                    self.assertNotEqual(attr, [])
                else:
                    self.assertIsInstance(attr, dict)
                    self.assertNotEqual(attr, {})

    def test_init_with_attributes(self):
        """Test the init with attributes."""
        generator = OCPGenerator(self.two_hours_ago, self.now, self.attributes)

        for attribute in ["nodes", "namespaces", "pods", "namespace2pods", "volumes"]:
            with self.subTest(attribute=attribute):
                attr = getattr(generator, attribute)
                self.assertIsNotNone(attr)

                if attribute in ("nodes", "volumes"):
                    self.assertIsInstance(attr, list)
                    self.assertNotEqual(attr, [])
                else:
                    self.assertIsInstance(attr, dict)
                    self.assertNotEqual(attr, {})

    def test_add_common_usage_info(self):
        """Test that add_common_usage_info updates usage timestamps."""
        generator = OCPGenerator(self.two_hours_ago, self.now, {})
        test_row = {}
        output_row = generator._add_common_usage_info(test_row, self.two_hours_ago, self.now)
        self.assertIn("interval_start", output_row)
        self.assertIn("interval_end", output_row)

    def test_gen_hourly_node_label_usage(self):
        """Test that gen_hourly_node_label_usage generates rows."""
        generator = OCPGenerator(self.two_hours_ago, self.now, self.attributes)
        namespaces = self.attributes.get("nodes")[0].get("namespaces")
        for dikt in namespaces.values():
            pods = dikt.get("pods")
            for pod in pods:
                with self.subTest(pod=pod):
                    for row in generator._gen_hourly_node_label_usage(report_type=OCP_NODE_LABEL, pod=pod):
                        self.assertIsInstance(row, dict)
                        for col in OCP_NODE_LABEL_COLUMNS:
                            with self.subTest(row=row):
                                with self.subTest(col=col):
                                    self.assertIn(col, row)
                                    self.assertIsNotNone(row[col])
                        break  # only test one row

    def test_gen_hourly_pods_usage(self):
        """Test that gen_hourly_pods_usage generates rows."""
        generator = OCPGenerator(self.two_hours_ago, self.now, self.attributes)
        namespaces = self.attributes.get("nodes")[0].get("namespaces")
        for dikt in namespaces.values():
            pods = dikt.get("pods")
            for pod in pods:
                with self.subTest(pod=pod):
                    for row in generator._gen_hourly_pods_usage(report_type=OCP_POD_USAGE):
                        self.assertIsInstance(row, dict)
                        for col in OCP_POD_USAGE_COLUMNS:
                            with self.subTest(row=row):
                                with self.subTest(col=col):
                                    self.assertIn(col, row)
                                    self.assertIsNotNone(row[col])
                        break  # only test one row

    def test_gen_hourly_storage_usage(self):
        """Test that gen_hourly_storage_usage generates rows."""
        generator = OCPGenerator(self.two_hours_ago, self.now, self.attributes)
        namespaces = self.attributes.get("nodes")[0].get("namespaces")
        for dikt in namespaces.values():
            pods = dikt.get("pods")
            for pod in pods:
                with self.subTest(pod=pod):
                    for row in generator._gen_hourly_storage_usage(report_type=OCP_STORAGE_USAGE):
                        self.assertIsInstance(row, dict)
                        for col in OCP_STORAGE_COLUMNS:
                            with self.subTest(row=row):
                                with self.subTest(col=col):
                                    self.assertIn(col, row)
                        # the following columns are not required to be not-null for claimless persistent-volumes
                        for col in set(OCP_STORAGE_COLUMNS).difference(
                            {
                                "namespace",
                                "pod",
                                "node",
                                "persistentvolumeclaim",
                                "volume_request_storage_byte_seconds",
                                "persistentvolumeclaim_usage_byte_seconds",
                                "persistentvolumeclaim_labels",
                            }
                        ):
                            with self.subTest(row=row):
                                with self.subTest(col=col):
                                    self.assertIsNotNone(row[col])

    def test_gen_namespaces_with_namespace(self):
        """Test that gen_namespaces arranges the output dict in the expected way.

        If namespaces are specified, namespaces are not generated.
        """
        in_nodes = self.attributes.get("nodes")
        generator = OCPGenerator(self.two_hours_ago, self.now, self.attributes)
        out_namespaces = generator._gen_namespaces(in_nodes)
        self.assertEqual(list(out_namespaces.keys()), list(in_nodes[0].get("namespaces").keys()))
        for value in out_namespaces.values():
            with self.subTest(node=value):
                self.assertEqual(list(value.get("namespaces").keys()), list(in_nodes[0].get("namespaces").keys()))

    def test_gen_namespaces_without_namespace(self):
        """Test that gen_namespaces arranges the output dict in the expected way.

        If no namespaces are specified, namespaces are generated.
        """
        in_nodes = self.attributes.get("nodes")
        del in_nodes[0]["namespaces"]
        generator = OCPGenerator(self.two_hours_ago, self.now, self.attributes)
        out_namespaces = generator._gen_namespaces(in_nodes)

        # auto-generating namespaces should create at least 2 namespaces
        self.assertGreater(len(list(out_namespaces.keys())), 1)

        for value in out_namespaces.values():
            with self.subTest(namespace=value):
                self.assertEqual(list(value.keys()), list(in_nodes[0].keys()))

    def test_gen_nodes_with_nodes(self):
        """Test that gen_nodes arranges the output dict in the expected way.

        If nodes are specified, nodes are not generated.
        """
        in_nodes = self.attributes.get("nodes")
        generator = OCPGenerator(self.two_hours_ago, self.now, self.attributes)
        out_nodes = generator._gen_nodes()
        self.assertEqual(len(list(out_nodes)), len(list(in_nodes)))
        expected_keys = ["name", "cpu_cores", "memory_bytes", "resource_id", "namespaces", "node_labels"]
        self.assertEqual(list(out_nodes[0].keys()), expected_keys)

    def test_gen_nodes_without_nodes(self):
        """Test that gen_nodes arranges the output dict in the expected way.

        If nodes are not specified, nodes are generated.
        """
        generator = OCPGenerator(self.two_hours_ago, self.now, {})
        out_nodes = generator._gen_nodes()
        self.assertGreaterEqual(len(list(out_nodes)), 2)
        self.assertLessEqual(len(list(out_nodes)), 6)
        expected_keys = ["name", "cpu_cores", "memory_bytes", "resource_id", "node_labels"]
        self.assertEqual(list(out_nodes[0].keys()), expected_keys)

    def test_gen_openshift_labels(self):
        """Test that gen_openshift_labels creates well-formatted labels."""
        generator = OCPGenerator(self.two_hours_ago, self.now, {})
        out_labels = generator._gen_openshift_labels()
        matcher = r"(\w+:\w+)((\|(\w+:\w+))+)?"
        self.assertRegex(out_labels, matcher)

    def test_gen_pods_with_namespaces(self):
        """Test that gen_pods arranges the output dict in the expected way.

        If namespaces with pods are specified, defined pods are used.
        """
        generator = OCPGenerator(self.two_hours_ago, self.now, self.attributes)
        out_pods, _, _ = generator._gen_pods(generator.namespaces)  # gen_pods depends on the output of gen_namespaces.
        self.assertEqual(len(out_pods), 2)

        expected = (
            "cpu_limit",
            "cpu_request",
            "cpu_usage",
            "interval_start",
            "interval_end",
            "mem_limit_gig",
            "mem_request_gig",
            "mem_usage_gig",
            "namespace",
            "node",
            "node_capacity_cpu_cores",
            "node_capacity_cpu_core_seconds",
            "node_capacity_memory_bytes",
            "node_capacity_memory_byte_seconds",
            "node_labels",
            "pod",
            "pod_labels",
            "pod_limit_cpu_core_seconds",
            "pod_limit_memory_byte_seconds",
            "pod_request_cpu_core_seconds",
            "pod_request_memory_byte_seconds",
            "pod_seconds",
            "pod_usage_cpu_core_seconds",
            "pod_usage_memory_byte_seconds",
            "report_period_start",
            "report_period_end",
            "resource_id",
        )
        for pod in out_pods.values():
            with self.subTest(podkeys=pod.keys()):
                for key in pod.keys():
                    with self.subTest(key=key):
                        self.assertIn(key, expected)

    def test_gen_pods_without_namespaces(self):
        """Test that gen_pods arranges the output dict in the expected way.

        If no namespaces are specified, pods are generated.
        """
        generator = OCPGenerator(self.two_hours_ago, self.now, {})
        out_pods, _, _ = generator._gen_pods(generator.namespaces)

        # these magic numbers are the random ranges defined in the OCP generator.
        self.assertGreaterEqual(len(out_pods), 2 * 2 * 2)
        self.assertLessEqual(len(out_pods), 6 * 12 * 20)

        # This list isn't quite the same as (OCP_POD_USAGE_COLUMNS + OCP_NODE_LABEL_COLUMNS + OCP_STORAGE_COLUMNS)
        # This might be a bug.
        expected = (
            "cpu_limit",
            "cpu_request",
            "cpu_usage",
            "interval_start",
            "interval_end",
            "mem_limit_gig",
            "mem_request_gig",
            "mem_usage_gig",
            "namespace",
            "node",
            "node_capacity_cpu_cores",
            "node_capacity_cpu_core_seconds",
            "node_capacity_memory_bytes",
            "node_capacity_memory_byte_seconds",
            "node_labels",
            "pod",
            "pod_labels",
            "pod_limit_cpu_core_seconds",
            "pod_limit_memory_byte_seconds",
            "pod_request_cpu_core_seconds",
            "pod_request_memory_byte_seconds",
            "pod_seconds",
            "pod_usage_cpu_core_seconds",
            "pod_usage_memory_byte_seconds",
            "report_period_start",
            "report_period_end",
            "resource_id",
        )
        for pod in out_pods.values():
            with self.subTest(podkeys=pod.keys()):
                for key in pod.keys():
                    with self.subTest(key=key):
                        self.assertIn(key, expected)

    def test_gen_pods_usage_lt_capacity(self):
        """Test that gen_pods generates requests and usage values which don't exceed limit."""
        for attributes in [self.attributes, {}]:
            with self.subTest(attributes=attributes):
                generator = OCPGenerator(self.two_hours_ago, self.now, attributes)
                # gen_pods depends on the output of gen_namespaces.
                out_pods, _, _ = generator._gen_pods(generator.namespaces)
                for pod in out_pods.values():
                    with self.subTest(pod=pod):
                        self.assertLessEqual(pod.get("cpu_limit"), pod.get("node_capacity_cpu_cores"))
                        self.assertLessEqual(pod.get("cpu_request"), pod.get("node_capacity_cpu_cores"))
                        self.assertLessEqual(pod.get("mem_limit_gig"), pod.get("node_capacity_memory_bytes"))
                        self.assertLessEqual(pod.get("mem_request_gig"), pod.get("node_capacity_memory_bytes"))
                        if attributes:
                            for value in pod.get("cpu_usage").values():
                                self.assertLessEqual(value, pod.get("node_capacity_cpu_cores"))
                            for value in pod.get("mem_usage_gig").values():
                                self.assertLessEqual(value, pod.get("node_capacity_memory_bytes"))

    def test_gen_volumes_with_namespaces(self):
        """Test that gen_volumes arranges the output dict in the expected way.

        If namespaces with volumes are specified, defined volumes are used.
        """
        generator = OCPGenerator(self.two_hours_ago, self.now, self.attributes)

        # gen_volumes depends on the output formatting of gen_namespaces and gen_pods.
        out_volumes = generator._gen_volumes(generator.namespaces, generator.namespace2pods)

        namespaces = self.attributes.get("nodes")[0].get("namespaces")
        volume_names = [vol.get("volume_name") for ns in namespaces for vol in namespaces.get(ns).get("volumes")]
        for vol_dict in out_volumes:
            self.assertTrue(all(v in volume_names for v in vol_dict.keys()))

        expected = [
            "node",
            "namespace",
            "volume",
            "storage_class",
            "csi_driver",
            "csi_volume_handle",
            "volume_request",
            "labels",
            "volume_claims",
        ]
        for vol_dict in out_volumes:
            for vol in vol_dict.values():
                with self.subTest(volume=vol):
                    self.assertEqual(list(vol.keys()), expected)

    def test_gen_volumes_without_namespaces(self):
        """Test that gen_volumes arranges the output dict in the expected way.

        If no namespaces are specified, volumes are generated.
        """
        generator = OCPGenerator(self.two_hours_ago, self.now, {})

        # gen_volumes depends on the output formatting of gen_namespaces and gen_pods.
        out_volumes = generator._gen_volumes(generator.namespaces, generator.namespace2pods)

        # these magic numbers are the random ranges defined in the OCP generator.
        self.assertGreaterEqual(len(out_volumes), 2 * 2 * 1)
        self.assertLessEqual(len(out_volumes), 6 * 12 * 3)

        expected = [
            "namespace",
            "node",
            "volume",
            "storage_class",
            "csi_driver",
            "csi_volume_handle",
            "volume_request",
            "labels",
            "volume_claims",
        ]
        for vol_dict in out_volumes:
            for vol in vol_dict.values():
                with self.subTest(volume=vol):
                    self.assertEqual(list(vol.keys()), expected)

    def test_gen_volumes_usage_lt_capacity(self):
        """Test that gen_volumes generates requests and usage values which don't exceed capacity."""
        for attributes in [self.attributes, {}]:
            with self.subTest(attributes=attributes):
                generator = OCPGenerator(self.two_hours_ago, self.now, attributes)
                for volume_dict in generator.volumes:
                    for volume in volume_dict.values():
                        with self.subTest(volume=volume):
                            total_capacity = 0
                            for claim in volume.get("volume_claims").values():
                                with self.subTest(claim=claim):
                                    capacity = claim.get("capacity")
                                    total_capacity += capacity

                                    if attributes:
                                        for value in claim.get("volume_claim_usage_gig").values():
                                            self.assertLessEqual(value * GIGABYTE, capacity)
                            self.assertLessEqual(total_capacity, volume.get("volume_request", MAX_VOL_GIGS * GIGABYTE))

    def test_gen_specific_volume_raises_valueerror_when_claims_exceed_request(self):
        """Test that _gen_specific_volume raises ValueError when total claims exceed volume request."""
        generator = OCPGenerator(self.two_hours_ago, self.now, {})

        # Create a fake node and namespace
        node = {"name": "test-node"}
        namespace = "test-namespace"

        # Create a volume specification where volume claims exceed the volume request
        specified_volume = {
            "volume_name": "test-volume",
            "volume_request_gig": 10,  # 10 GiB volume request
            "volume_claims": [
                {
                    "volume_claim_name": "claim1",
                    "pod_name": "pod1",
                    "capacity_gig": 8,  # 8 GiB claim
                },
                {
                    "volume_claim_name": "claim2",
                    "pod_name": "pod2",
                    "capacity_gig": 5,  # 5 GiB claim - total 13 GiB > 10 GiB request
                },
            ],
        }

        # Verify that ValueError is raised with expected message
        with self.assertRaises(ValueError) as context:
            generator._gen_specific_volume(node, namespace, specified_volume)

        expected_total_claims = (8 + 5) * GIGABYTE  # 13 GiB in bytes
        expected_volume_request = 10 * GIGABYTE  # 10 GiB in bytes
        expected_message = (
            f"Total claims {expected_total_claims} is greater than volume request {expected_volume_request}"
        )

        self.assertEqual(str(context.exception), expected_message)

    def test_generate_hourly_data(self):
        """Test that generate_hourly_data calls the test method."""
        generator = OCPGenerator(self.two_hours_ago, self.now, self.attributes)
        test_method1 = Mock(return_value=True)
        test_method2 = Mock(return_value=True)
        with patch.dict(
            generator.ocp_report_generation,
            {"test_report": {"_generate_hourly_data": test_method1, "_update_data": test_method2}},
        ):
            kwargs = {"report_type": "test_report"}
            generator._generate_hourly_data(**kwargs)
            test_method1.assert_called_with(**kwargs)
            test_method2.assert_not_called()

    def test_get_usage_for_date(self):
        """Test that get_usage_for_date returns selected data."""
        test_usage = self._usage_dict()
        start_date = random.choice(list(test_usage.keys()))
        output = OCPGenerator._get_usage_for_date(test_usage, datetime.strptime(start_date, "%m-%d-%Y"))
        self.assertEqual(output, test_usage.get(start_date))

    def test_init_data_row(self):
        """Test that init_data_row initializes a row of data."""
        generator = OCPGenerator(self.two_hours_ago, self.now, self.attributes)

        for report_type, columns in [
            (OCP_POD_USAGE, OCP_POD_USAGE_COLUMNS),
            (OCP_NODE_LABEL, OCP_NODE_LABEL_COLUMNS),
            (OCP_STORAGE_USAGE, OCP_STORAGE_COLUMNS),
        ]:
            with self.subTest(report_type=report_type):
                row = generator._init_data_row(self.two_hours_ago, self.now, report_type=report_type)
                self.assertIsInstance(row, dict)
                self.assertEqual(list(row.keys()), list(columns))

    def test_update_data(self):
        """Test that update_data calls the expected update method."""
        generator = OCPGenerator(self.two_hours_ago, self.now, self.attributes)
        test_method1 = Mock(return_value=True)
        test_method2 = Mock(return_value=True)
        with patch.dict(
            generator.ocp_report_generation,
            {"test_report": {"_generate_hourly_data": test_method1, "_update_data": test_method2}},
        ):
            kwargs = {"report_type": "test_report"}
            generator._update_data({}, self.two_hours_ago, self.now, **kwargs)
            test_method2.assert_called_with(
                {
                    "interval_start": self.two_hours_ago.strftime("%Y-%m-%d %H:%M:%S +0000 UTC"),
                    "interval_end": self.now.strftime("%Y-%m-%d %H:%M:%S +0000 UTC"),
                },
                self.two_hours_ago,
                self.now,
                **kwargs,
            )
            test_method1.assert_not_called()

    def test_update_node_label_data(self):
        """Test that _update_node_label_data updates label data"""
        node = self.attributes.get("nodes")[0]
        kwargs = {"node": node.get("node"), "node_labels": node.get("node_labels")}

        generator = OCPGenerator(self.two_hours_ago, self.now, {})
        in_row = generator._init_data_row(self.two_hours_ago, self.now, report_type=OCP_NODE_LABEL)
        out_row = generator._update_node_label_data(copy(in_row), self.two_hours_ago, self.now, **kwargs)

        self.assertEqual(out_row.get("node"), node.get("node"))
        self.assertNotEqual(out_row.get("node"), in_row.get("node"))
        self.assertEqual(out_row.get("node_labels"), node.get("node_labels"))
        self.assertNotEqual(out_row.get("node_labels"), in_row.get("node_labels"))

    def test_update_pod_data(self):
        """Test that _update_pod_data updates pod data"""
        pods = next(iter(self.attributes.get("nodes")[0].get("namespaces").values())).get("pods")
        kwargs = {
            "cpu_usage": self._usage_dict(),
            "mem_usage_gig": self._usage_dict(),
            "pod_seconds": 86400,
            "pod": pods[0],
        }
        changed = {
            "pod_usage_cpu_core_seconds",
            "pod_request_cpu_core_seconds",
            "pod_limit_cpu_core_seconds",
            "pod_usage_memory_byte_seconds",
            "pod_request_memory_byte_seconds",
            "pod_limit_memory_byte_seconds",
        }

        generator = OCPGenerator(self.two_hours_ago, self.now, {})
        in_row = generator._init_data_row(self.two_hours_ago, self.now, report_type=OCP_POD_USAGE)
        out_row = generator._update_pod_data(copy(in_row), self.two_hours_ago, self.now, **kwargs)

        for key in changed:
            with self.subTest(key=key):
                self.assertEqual(out_row.get(key), pods[0].get(key))
                self.assertNotEqual(out_row.get(key), in_row.get(key))

        for key in list(set(out_row.keys()) - changed):
            with self.subTest(key=key):
                self.assertIn(out_row.get(key), [pods[0].get(key), in_row.get(key)])

    def test_update_pod_data_usage_lt_limit(self):
        """Test that _update_pod_data keeps usage <= request <= limit."""
        pods = next(iter(self.attributes.get("nodes")[0].get("namespaces").values())).get("pods")
        kwargs = {
            "cpu_usage": self._usage_dict(),
            "mem_usage_gig": self._usage_dict(),
            "pod_seconds": 86400,
            "pod": pods[0],
        }

        generator = OCPGenerator(self.two_hours_ago, self.now, {})
        in_row = generator._init_data_row(self.two_hours_ago, self.now, report_type=OCP_POD_USAGE)
        out_row = generator._update_pod_data(copy(in_row), self.two_hours_ago, self.now, **kwargs)

        for x in ["cpu_core", "memory_byte"]:
            with self.subTest(row=out_row):
                with self.subTest(x=x):
                    self.assertLessEqual(out_row.get(f"pod_usage_{x}_seconds"), out_row.get(f"pod_limit_{x}_seconds"))
                    self.assertLessEqual(out_row.get(f"pod_usage_{x}_seconds"), out_row.get(f"pod_limit_{x}_seconds"))
                    self.assertLessEqual(out_row.get(f"pod_request_{x}_seconds"), out_row.get(f"pod_limit_{x}_seconds"))

    def test_update_storage_data(self):
        """Test that _update_storage_data updates storage data."""
        kwargs = {
            "volume_claim_usage_gig": self._usage_dict(),
            "vc_capacity": self.fake.pyint(1, 100),
            "namespace": self.fake.word(),
            "pod": self.fake.word(),
            "volume_claim": self.fake.uuid4(),
            "volume_name": self.fake.word(),
            "storage_class": self.fake.word(),
            "volume_request": self.fake.pyint(1, 100),
            "volume_labels": (
                f"label_{self.fake.word()}:{self.fake.word()}",
                f"|label_{self.fake.word()}:{self.fake.word()}",
            ),
            "volume_claim_labels": (
                f"label_{self.fake.word()}:{self.fake.word()}",
                f"|label_{self.fake.word()}:{self.fake.word()}",
            ),
        }
        changed = {
            "namespace",
            "pod",
            "persistentvolumeclaim",
            "persistentvolume",
            "storageclass",
            "csi_driver",
            "csi_volume_handle",
            "persistentvolumeclaim_capacity_bytes",
            "persistentvolumeclaim_capacity_byte_seconds",
            "volume_request_storage_byte_seconds",
            "persistentvolume_labels",
            "persistentvolumeclaim_labels",
            "persistentvolumeclaim_usage_byte_seconds",
        }

        generator = OCPGenerator(self.two_hours_ago, self.now, {})
        in_row = generator._init_data_row(self.two_hours_ago, self.now, report_type=OCP_STORAGE_USAGE)
        out_row = generator._update_storage_data(copy(in_row), self.two_hours_ago, self.now, **kwargs)

        for key in changed:
            with self.subTest(key=key):
                if key in kwargs:
                    self.assertEqual(out_row.get(key), kwargs.get(key))
                self.assertNotEqual(out_row.get(key), in_row.get(key))

        for key in list(set(out_row.keys()) - changed):
            with self.subTest(key=key):
                self.assertIn(out_row.get(key), [kwargs.get(key), in_row.get(key)])

    def test_update_storage_data_usage_lt_capacity(self):
        """Test that _update_storge_data keeps usage <= request <= capacity."""
        request = self.fake.pyint(1, 100)
        kwargs = {
            "volume_claim_usage_gig": self._usage_dict(),
            "vc_capacity": self.fake.pyint(request, 100),
            "namespace": self.fake.word(),
            "pod": self.fake.word(),
            "volume_claim": self.fake.uuid4(),
            "volume_name": self.fake.word(),
            "storage_class": self.fake.word(),
            "volume_request": request,
            "volume_labels": (
                f"label_{self.fake.word()}:{self.fake.word()}",
                f"|label_{self.fake.word()}:{self.fake.word()}",
            ),
            "volume_claim_labels": (
                f"label_{self.fake.word()}:{self.fake.word()}",
                f"|label_{self.fake.word()}:{self.fake.word()}",
            ),
        }

        generator = OCPGenerator(self.two_hours_ago, self.now, {})
        in_row = generator._init_data_row(self.two_hours_ago, self.now, report_type=OCP_STORAGE_USAGE)
        out_row = generator._update_storage_data(copy(in_row), self.two_hours_ago, self.now, **kwargs)

        self.assertLessEqual(
            out_row.get("persistentvolumeclaim_usage_byte_seconds"),
            out_row.get("volume_request_storage_byte_seconds") * GIGABYTE,
        )
        self.assertLessEqual(
            out_row.get("volume_request_storage_byte_seconds"),
            out_row.get("persistentvolumeclaim_capacity_byte_seconds"),
        )

    def test_generate_data(self):
        """Test that generate_data calls the test method."""
        generator = OCPGenerator(self.two_hours_ago, self.now, self.attributes)
        with patch.object(generator, "_generate_hourly_data") as mock_method:
            kwargs = {"report_type": "test_report"}
            generator.generate_data(**kwargs)
            mock_method.assert_called_with(**kwargs)

    def test_timestamp_valid(self):
        """Test that timestamp returns a string with a valid input."""
        self.assertIsInstance(OCPGenerator.timestamp(self.now), str)

    def test_timestamp_invalid(self):
        """Test that timestamp raises a ValueError with invalid input."""
        with self.assertRaises(ValueError):
            OCPGenerator.timestamp(self.fake.word())

    def test_get_vm_disk_default_values(self):
        """Test get_vm_disk with default values."""
        generator = OCPGenerator(self.two_hours_ago, self.now, {})

        with (
            patch("nise.generators.ocp.ocp_generator.FAKER") as mock_faker,
            patch("nise.generators.ocp.ocp_generator.randint") as mock_randint,
        ):
            mock_faker.word.return_value = "test-pvc"
            mock_randint.return_value = 40

            result = generator.get_vm_disk()

            expected = {
                "vm_device": "rootdisk",
                "vm_volume_mode": "Block",
                "vm_persistentvolumeclaim_name": "test-pvc",
                "vc_capacity": 40 * GIGABYTE,
            }
            self.assertEqual(result, expected)

    def test_get_vm_disk_with_specified_vc_device_and_mode(self):
        """Test get_vm_disk with specified device and volume mode."""
        generator = OCPGenerator(self.two_hours_ago, self.now, {})

        specified_vc = {
            "vol_device": "datadisk",
            "volume_mode": "Filesystem",
        }

        with (
            patch("nise.generators.ocp.ocp_generator.FAKER") as mock_faker,
            patch("nise.generators.ocp.ocp_generator.randint") as mock_randint,
        ):
            mock_faker.word.return_value = "test-pvc"
            mock_randint.return_value = 35

            result = generator.get_vm_disk(specified_vc=specified_vc)

            expected = {
                "vm_device": "datadisk",
                "vm_volume_mode": "Filesystem",
                "vm_persistentvolumeclaim_name": "test-pvc",
                "vc_capacity": 35 * GIGABYTE,
            }
            self.assertEqual(result, expected)

    def test_get_vm_disk_with_pod_name_found_pvc(self):
        """Test get_vm_disk with pod_name that has an associated PVC."""
        generator = OCPGenerator(self.two_hours_ago, self.now, {})

        # Mock the get_specific_pvc_from_pod method to return a PVC
        mock_pvc = {"capacity": 50 * GIGABYTE}
        with patch.object(generator, "get_specific_pvc_from_pod", return_value=("test-pvc-name", mock_pvc)):
            result = generator.get_vm_disk(pod_name="test-pod")

            expected = {
                "vm_device": "rootdisk",
                "vm_volume_mode": "Block",
                "vm_persistentvolumeclaim_name": "test-pvc-name",
                "vc_capacity": 50 * GIGABYTE,
            }
            self.assertEqual(result, expected)

    def test_get_vm_disk_with_specified_vc_pod_name_found_pvc(self):
        """Test get_vm_disk with pod_name in specified_vc that has an associated PVC."""
        generator = OCPGenerator(self.two_hours_ago, self.now, {})

        specified_vc = {
            "pod_name": "test-pod-from-vc",
            "vol_device": "mydisk",
        }

        mock_pvc = {"capacity": 75 * GIGABYTE}
        with patch.object(generator, "get_specific_pvc_from_pod", return_value=("vc-pvc-name", mock_pvc)):
            result = generator.get_vm_disk(specified_vc=specified_vc)

            expected = {
                "vm_device": "mydisk",
                "vm_volume_mode": "Block",
                "vm_persistentvolumeclaim_name": "vc-pvc-name",
                "vc_capacity": 75 * GIGABYTE,
            }
            self.assertEqual(result, expected)

    def test_get_vm_disk_pod_name_no_pvc_static_report_true(self):
        """Test get_vm_disk with pod_name but no PVC and static_report=True."""
        generator = OCPGenerator(self.two_hours_ago, self.now, {})

        # Mock to return no PVC
        with patch.object(generator, "get_specific_pvc_from_pod", return_value=("", {})):
            result = generator.get_vm_disk(pod_name="test-pod", static_report=True)

            self.assertEqual(result, {})

    def test_get_vm_disk_pod_name_no_pvc_static_report_false(self):
        """Test get_vm_disk with pod_name but no PVC and static_report=False."""
        generator = OCPGenerator(self.two_hours_ago, self.now, {})

        with (
            patch.object(generator, "get_specific_pvc_from_pod", return_value=("", {})),
            patch("nise.generators.ocp.ocp_generator.FAKER") as mock_faker,
            patch("nise.generators.ocp.ocp_generator.randint") as mock_randint,
        ):
            mock_faker.word.return_value = "fallback-pvc"
            mock_randint.return_value = 45

            result = generator.get_vm_disk(pod_name="test-pod", static_report=False)

            expected = {
                "vm_device": "rootdisk",
                "vm_volume_mode": "Block",
                "vm_persistentvolumeclaim_name": "fallback-pvc",
                "vc_capacity": 45 * GIGABYTE,
            }
            self.assertEqual(result, expected)

    def test_get_vm_disk_with_specified_vc_volume_claim_and_capacity(self):
        """Test get_vm_disk with specified volume_claim_name and capacity_gig."""
        generator = OCPGenerator(self.two_hours_ago, self.now, {})

        specified_vc = {
            "volume_claim_name": "custom-pvc",
            "capacity_gig": 100,
            "vol_device": "storage",
            "volume_mode": "Filesystem",
        }

        result = generator.get_vm_disk(specified_vc=specified_vc)

        expected = {
            "vm_device": "storage",
            "vm_volume_mode": "Filesystem",
            "vm_persistentvolumeclaim_name": "custom-pvc",
            "vc_capacity": 100 * GIGABYTE,
        }
        self.assertEqual(result, expected)

    def test_get_vm_disk_pod_name_priority_over_parameter(self):
        """Test that pod_name in specified_vc takes priority over pod_name parameter."""
        generator = OCPGenerator(self.two_hours_ago, self.now, {})

        specified_vc = {
            "pod_name": "priority-pod",
        }

        mock_pvc = {"capacity": 60 * GIGABYTE}
        with patch.object(generator, "get_specific_pvc_from_pod") as mock_get_pvc:
            mock_get_pvc.return_value = ("priority-pvc", mock_pvc)

            result = generator.get_vm_disk(specified_vc=specified_vc, pod_name="ignored-pod")

            # Should call with priority-pod, not ignored-pod
            mock_get_pvc.assert_called_once_with("priority-pod")

            expected = {
                "vm_device": "rootdisk",
                "vm_volume_mode": "Block",
                "vm_persistentvolumeclaim_name": "priority-pvc",
                "vc_capacity": 60 * GIGABYTE,
            }
            self.assertEqual(result, expected)

    def test_get_vm_disk_parameter_pod_name_when_no_vc_pod_name(self):
        """Test that pod_name parameter is used when specified_vc has no pod_name."""
        generator = OCPGenerator(self.two_hours_ago, self.now, {})

        specified_vc = {
            "vol_device": "testdisk",
        }

        mock_pvc = {"capacity": 80 * GIGABYTE}
        with patch.object(generator, "get_specific_pvc_from_pod") as mock_get_pvc:
            mock_get_pvc.return_value = ("param-pvc", mock_pvc)

            result = generator.get_vm_disk(specified_vc=specified_vc, pod_name="param-pod")

            # Should call with param-pod
            mock_get_pvc.assert_called_once_with("param-pod")

            expected = {
                "vm_device": "testdisk",
                "vm_volume_mode": "Block",
                "vm_persistentvolumeclaim_name": "param-pvc",
                "vc_capacity": 80 * GIGABYTE,
            }
            self.assertEqual(result, expected)

    def test_get_vm_disk_empty_pod_name_values(self):
        """Test get_vm_disk with empty pod_name values."""
        generator = OCPGenerator(self.two_hours_ago, self.now, {})

        specified_vc = {
            "pod_name": "",  # Empty string
        }

        with (
            patch("nise.generators.ocp.ocp_generator.FAKER") as mock_faker,
            patch("nise.generators.ocp.ocp_generator.randint") as mock_randint,
        ):
            mock_faker.word.return_value = "empty-pvc"
            mock_randint.return_value = 42

            result = generator.get_vm_disk(specified_vc=specified_vc, pod_name="")

            expected = {
                "vm_device": "rootdisk",
                "vm_volume_mode": "Block",
                "vm_persistentvolumeclaim_name": "empty-pvc",
                "vc_capacity": 42 * GIGABYTE,
            }
            self.assertEqual(result, expected)

    def test_get_vm_disk_randint_range(self):
        """Test that get_vm_disk uses correct randint range for capacity."""
        generator = OCPGenerator(self.two_hours_ago, self.now, {})

        with (
            patch("nise.generators.ocp.ocp_generator.FAKER") as mock_faker,
            patch("nise.generators.ocp.ocp_generator.randint") as mock_randint,
        ):
            mock_faker.word.return_value = "test-pvc"
            mock_randint.return_value = 35

            generator.get_vm_disk()

            # Verify randint was called with correct range (30, 50)
            mock_randint.assert_called_once_with(30, 50)

    def test_ros_namespace_usage_columns_defined(self):
        """Test that ROS namespace usage columns are properly defined in the correct order."""
        self.assertEqual(len(OCP_ROS_NAMESPACE_USAGE_COLUMN), 29)

        # Expected columns in the exact order specified in the original requirements
        expected_columns_in_order = (
            "report_period_start",
            "report_period_end",
            "interval_start",
            "interval_end",
            "namespace",
            "cpu_request_namespace_sum",
            "cpu_request_namespace_used",
            "cpu_limit_namespace_sum",
            "cpu_limit_namespace_used",
            "cpu_usage_namespace_avg",
            "cpu_usage_namespace_max",
            "cpu_usage_namespace_min",
            "cpu_throttle_namespace_avg",
            "cpu_throttle_namespace_max",
            "cpu_throttle_namespace_min",
            "memory_request_namespace_sum",
            "memory_request_namespace_used",
            "memory_limit_namespace_sum",
            "memory_limit_namespace_used",
            "memory_usage_namespace_avg",
            "memory_usage_namespace_max",
            "memory_usage_namespace_min",
            "memory_rss_usage_namespace_avg",
            "memory_rss_usage_namespace_max",
            "memory_rss_usage_namespace_min",
            "namespace_running_pods_max",
            "namespace_running_pods_avg",
            "namespace_total_pods_max",
            "namespace_total_pods_avg",
        )

        # Test 1: Verify exact order and length
        self.assertEqual(OCP_ROS_NAMESPACE_USAGE_COLUMN, expected_columns_in_order)

        # Test 2: Verify each column is present (redundant but explicit)
        for column in expected_columns_in_order:
            with self.subTest(column=column):
                self.assertIn(column, OCP_ROS_NAMESPACE_USAGE_COLUMN)

        # Test 3: Verify specific column positions for key fields
        key_positions = {
            "namespace": 4,
            "cpu_request_namespace_sum": 5,
            "cpu_request_namespace_used": 6,
            "memory_request_namespace_sum": 15,
            "memory_request_namespace_used": 16,
            "namespace_running_pods_max": 25,
            "namespace_total_pods_avg": 28,
        }

        for column_name, expected_position in key_positions.items():
            with self.subTest(column=column_name, position=expected_position):
                actual_position = OCP_ROS_NAMESPACE_USAGE_COLUMN.index(column_name)
                self.assertEqual(
                    actual_position,
                    expected_position,
                    f"Column '{column_name}' should be at position {expected_position}, "
                    f"but found at position {actual_position}",
                )

    def test_ros_cluster_quota_columns_defined(self):
        """Test that ClusterResourceQuota columns are defined in the expected order."""
        expected_columns = (
            "report_period_start",
            "report_period_end",
            "interval_start",
            "interval_end",
            "cluster_quota_name",
            "cpu_request_hard",
            "cpu_request_used",
            "cpu_limit_hard",
            "cpu_limit_used",
            "memory_request_hard",
            "memory_request_used",
            "memory_limit_hard",
            "memory_limit_used",
            "storage_request_hard",
            "storage_request_used",
            "pods_hard",
            "pods_used",
            "object_count_hard",
            "object_count_used",
            "namespaces",
        )
        self.assertEqual(len(OCP_ROS_CLUSTER_QUOTA_COLUMN), 20)
        self.assertEqual(OCP_ROS_CLUSTER_QUOTA_COLUMN, expected_columns)

    def test_cluster_quota_hard_and_used_values(self):
        """Test CRQ hard/used generation from static YAML-style config."""
        quota_config = {
            "name": "team-frontend",
            "cpu_request_hard": 20,
            "cpu_limit_hard": 40,
            "memory_request_hard_gig": 50,
            "memory_limit_hard_gig": 100,
            "cpu_request_used": 12,
            "memory_request_used_gig": 30,
        }
        values = cluster_quota_hard_and_used_values(quota_config, constant_values_ros_ocp=True)
        self.assertEqual(values["cluster_quota_name"], "team-frontend")
        self.assertEqual(values["cpu_request_hard"], 20)
        self.assertEqual(values["cpu_request_used"], 12)
        self.assertEqual(values["cpu_limit_hard"], 40)
        self.assertEqual(values["memory_request_hard"], 50 * 1024 * 1024 * 1024)
        self.assertEqual(values["memory_request_used"], 30 * 1024 * 1024 * 1024)
        self.assertLessEqual(values["cpu_limit_used"], values["cpu_limit_hard"])
        self.assertLessEqual(values["memory_limit_used"], values["memory_limit_hard"])
        self.assertEqual(values["pods_hard"], 50)
        self.assertEqual(values["pods_used"], 20)
        self.assertEqual(values["namespaces"], "namespace-1,namespace-2")

    def test_gen_ros_cluster_quota_rows_default_quotas(self):
        """Test default ClusterResourceQuota row generation."""
        generator = OCPGenerator(self.two_hours_ago, self.now, {}, ros_ocp_info=True)
        results = list(generator._gen_ros_cluster_quota_rows())
        self.assertEqual(len(results), 3)
        names = {row["cluster_quota_name"] for row in results}
        self.assertEqual(names, {"team-frontend", "team-backend", "team-platform"})
        for row in results:
            self.assertGreater(row["cpu_request_hard"], 0)
            self.assertGreater(row["memory_request_hard"], 0)
            self.assertGreaterEqual(row["cpu_request_used"], row["cpu_request_hard"] * 0.3)
            self.assertLessEqual(row["cpu_request_used"], row["cpu_request_hard"])
            self.assertGreaterEqual(row["memory_request_used"], row["memory_request_hard"] * 0.3)
            self.assertLessEqual(row["memory_request_used"], row["memory_request_hard"])
            self.assertIn("storage_request_hard", row)
            self.assertIn("namespaces", row)
            self.assertEqual(row["pods_hard"], 50)

    def test_gen_ros_cluster_quota_rows_from_static_yaml(self):
        """Test ClusterResourceQuota rows from static YAML attributes."""
        attributes = {
            "cluster_resource_quotas": [
                {
                    "name": "team-custom",
                    "cpu_request_hard": 25,
                    "cpu_limit_hard": 50,
                    "memory_request_hard_gig": 80,
                    "memory_limit_hard_gig": 160,
                }
            ]
        }
        generator = OCPGenerator(self.two_hours_ago, self.now, attributes, ros_ocp_info=True)
        results = list(generator._gen_ros_cluster_quota_rows())
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["cluster_quota_name"], "team-custom")
        self.assertEqual(results[0]["cpu_request_hard"], 25)

    def test_init_with_ros_ocp_info(self):
        """Test that generator initializes correctly with ros_ocp_info enabled."""
        generator = OCPGenerator(self.two_hours_ago, self.now, {}, ros_ocp_info=True)

        self.assertIn(OCP_ROS_NAMESPACE_USAGE, generator.ocp_report_generation)
        self.assertIn(OCP_ROS_CLUSTER_QUOTA, generator.ocp_report_generation)

        ros_namespace_config = generator.ocp_report_generation[OCP_ROS_NAMESPACE_USAGE]
        self.assertIn("_generate_hourly_data", ros_namespace_config)
        self.assertIn("_update_data", ros_namespace_config)

    def test_gen_quarter_hourly_ros_ocp_namespace_usage(self):
        """Test that _gen_quarter_hourly_ros_ocp_namespace_usage generates correct data."""
        generator = OCPGenerator(self.two_hours_ago, self.now, {}, ros_ocp_info=True)

        generator.ros_data = {
            "pod1": {"namespace": "ns1", "cpu_request_container_sum": 1.0},
            "pod2": {"namespace": "ns1", "cpu_request_container_sum": 2.0},
            "pod3": {"namespace": "ns2", "cpu_request_container_sum": 3.0},
        }

        def mock_aggregate(namespace, start, end):
            return {
                "namespace": namespace,
                "cpu_request_namespace_sum": 5.0,
                "interval_start": start,
                "interval_end": end,
            }

        with patch.object(generator, "_aggregate_namespace_data", side_effect=mock_aggregate):
            results = list(generator._gen_quarter_hourly_ros_ocp_namespace_usage())

        self.assertEqual(len(results), 16)

        namespaces = [result["namespace"] for result in results]
        self.assertIn("ns1", namespaces)
        self.assertIn("ns2", namespaces)

        self.assertEqual(namespaces.count("ns1"), 8)
        self.assertEqual(namespaces.count("ns2"), 8)

    def test_update_ros_ocp_namespace_data(self):
        """Test that _update_ros_ocp_namespace_data updates row correctly."""
        generator = OCPGenerator(self.two_hours_ago, self.now, {}, ros_ocp_info=True)

        row = {"namespace": "", "cpu_request_namespace_sum": 0}

        mock_data = {
            "namespace": "test-namespace",
            "cpu_request_namespace_sum": 10.0,
            "memory_limit_namespace_sum": 2048,
        }

        with patch.object(generator, "_aggregate_namespace_data", return_value=mock_data):
            updated_row = generator._update_ros_ocp_namespace_data(
                row, self.two_hours_ago, self.now, namespace="test-namespace"
            )

        self.assertEqual(updated_row["namespace"], "test-namespace")
        self.assertEqual(updated_row["cpu_request_namespace_sum"], 10.0)
        self.assertEqual(updated_row["memory_limit_namespace_sum"], 2048)

    def test_init_with_ros_only(self):
        """Test that generator initializes correctly with ros_only enabled."""
        generator = OCPGenerator(self.two_hours_ago, self.now, {}, ros_only=True)

        # Should have ONLY ROS reports in ocp_report_generation
        self.assertEqual(len(generator.ocp_report_generation), 3)
        self.assertIn(OCP_ROS_USAGE, generator.ocp_report_generation)
        self.assertIn(OCP_ROS_NAMESPACE_USAGE, generator.ocp_report_generation)
        self.assertIn(OCP_ROS_CLUSTER_QUOTA, generator.ocp_report_generation)

        # Should NOT have standard reports
        self.assertNotIn(OCP_POD_USAGE, generator.ocp_report_generation)
        self.assertNotIn(OCP_STORAGE_USAGE, generator.ocp_report_generation)
        self.assertNotIn(OCP_NODE_LABEL, generator.ocp_report_generation)
        self.assertNotIn(OCP_NAMESPACE_LABEL, generator.ocp_report_generation)
        self.assertNotIn(OCP_VM_USAGE, generator.ocp_report_generation)
        self.assertNotIn(OCP_GPU_USAGE, generator.ocp_report_generation)

        ros_usage_config = generator.ocp_report_generation[OCP_ROS_USAGE]
        self.assertIn("_generate_hourly_data", ros_usage_config)
        self.assertIn("_update_data", ros_usage_config)

        ros_namespace_config = generator.ocp_report_generation[OCP_ROS_NAMESPACE_USAGE]
        self.assertIn("_generate_hourly_data", ros_namespace_config)
        self.assertIn("_update_data", ros_namespace_config)

    def test_ocp_report_type_to_cols_includes_namespace_usage(self):
        """Test that OCP_REPORT_TYPE_TO_COLS includes namespace usage mapping and verify separation."""
        # Test merged dictionary includes namespace usage
        self.assertIn(OCP_ROS_NAMESPACE_USAGE, OCP_REPORT_TYPE_TO_COLS)
        self.assertEqual(OCP_REPORT_TYPE_TO_COLS[OCP_ROS_NAMESPACE_USAGE], OCP_ROS_NAMESPACE_USAGE_COLUMN)

        # Test separation: namespace usage should be in ROS dict, not in COST dict
        self.assertIn(OCP_ROS_NAMESPACE_USAGE, ROS_OCP_REPORT_TYPE_TO_COLS)
        self.assertIn(OCP_ROS_CLUSTER_QUOTA, ROS_OCP_REPORT_TYPE_TO_COLS)
        self.assertEqual(ROS_OCP_REPORT_TYPE_TO_COLS[OCP_ROS_CLUSTER_QUOTA], OCP_ROS_CLUSTER_QUOTA_COLUMN)
        self.assertNotIn(OCP_ROS_NAMESPACE_USAGE, COST_OCP_REPORT_TYPE_TO_COLS)
        self.assertNotIn(OCP_ROS_CLUSTER_QUOTA, COST_OCP_REPORT_TYPE_TO_COLS)

        # Test that cost-related reports are in COST dict
        self.assertIn(OCP_POD_USAGE, COST_OCP_REPORT_TYPE_TO_COLS)
        self.assertIn(OCP_STORAGE_USAGE, COST_OCP_REPORT_TYPE_TO_COLS)

        # Test that ROS reports are not in COST dict
        self.assertNotIn(OCP_ROS_USAGE, COST_OCP_REPORT_TYPE_TO_COLS)
        self.assertNotIn(OCP_ROS_NAMESPACE_USAGE, COST_OCP_REPORT_TYPE_TO_COLS)

    def test_gen_quarter_hourly_ros_ocp_namespace_usage_empty_ros_data(self):
        """Test _gen_quarter_hourly_ros_ocp_namespace_usage with empty ros_data.

        Verifies that an empty generator.ros_data results in no output
        and no exceptions from _gen_quarter_hourly_ros_ocp_namespace_usage.
        """
        generator = OCPGenerator(self.two_hours_ago, self.now, {}, ros_ocp_info=True)

        generator.ros_data = {}

        results = list(generator._gen_quarter_hourly_ros_ocp_namespace_usage())

        self.assertEqual(len(results), 0)
        self.assertEqual(results, [])

    def test_update_ros_ocp_namespace_data_missing_namespace_kwargs(self):
        """Test _update_ros_ocp_namespace_data with missing namespace in kwargs.

        Verifies that _update_ros_ocp_namespace_data handles the absence
        of 'namespace' key in kwargs correctly.
        """
        generator = OCPGenerator(self.two_hours_ago, self.now, {}, ros_ocp_info=True)
        row = {
            "namespace": "",
            "cpu_request_namespace_sum": 0,
            "memory_limit_namespace_sum": 0,
        }

        generator.ros_data = {"pod1": {"namespace": "test-ns", "cpu_request_container_sum": 1.0}}

        with patch.object(generator, "_aggregate_namespace_data", return_value={}) as mock_aggregate:
            updated_row = generator._update_ros_ocp_namespace_data(row, self.two_hours_ago, self.now)

            mock_aggregate.assert_called_once_with("", self.two_hours_ago, self.now)
            self.assertEqual(updated_row["namespace"], "")
            self.assertEqual(updated_row["cpu_request_namespace_sum"], 0)

    def test_aggregate_namespace_data_no_pods_for_namespace(self):
        """Test _aggregate_namespace_data when no pods exist for a namespace.

        Verifies that _aggregate_namespace_data returns appropriate default values
        when the namespace is missing from ros_data.
        """
        generator = OCPGenerator(self.two_hours_ago, self.now, {}, ros_ocp_info=True)

        generator.ros_data = {
            "pod1": {"namespace": "existing-namespace", "cpu_request_container_sum": 1.0},
            "pod2": {"namespace": "existing-namespace", "memory_limit_container_sum": 2048},
        }

        result = generator._aggregate_namespace_data("non-existent-namespace", self.two_hours_ago, self.now)
        self.assertIsInstance(result, dict)
        self.assertEqual(result, {})
        self.assertEqual(len(result), 0)

    def test_aggregate_namespace_data_includes_quota_used_columns(self):
        """Test that aggregated namespace data includes ResourceQuota used columns."""
        generator = OCPGenerator(self.two_hours_ago, self.now, {}, ros_ocp_info=True)
        generator.ros_data = {
            "pod1": {
                "namespace": "quota-ns",
                "cpu_request_container_sum": 4.0,
                "cpu_limit_container_sum": 8.0,
                "cpu_usage_container_avg": 1.0,
                "cpu_usage_container_min": 0.5,
                "cpu_usage_container_max": 1.5,
                "cpu_throttle_container_avg": 0.0,
                "cpu_throttle_container_max": 0.0,
                "memory_request_container_sum": 2 * 1024 * 1024 * 1024,
                "memory_limit_container_sum": 4 * 1024 * 1024 * 1024,
                "memory_usage_container_avg": 1024 * 1024 * 1024,
                "memory_usage_container_min": 512 * 1024 * 1024,
                "memory_usage_container_max": 1536 * 1024 * 1024,
                "memory_rss_usage_container_avg": 900 * 1024 * 1024,
                "memory_rss_usage_container_min": 400 * 1024 * 1024,
                "memory_rss_usage_container_max": 1000 * 1024 * 1024,
            },
        }

        result = generator._aggregate_namespace_data("quota-ns", self.two_hours_ago, self.now)

        for column in (
            "cpu_request_namespace_used",
            "cpu_limit_namespace_used",
            "memory_request_namespace_used",
            "memory_limit_namespace_used",
        ):
            with self.subTest(column=column):
                self.assertIn(column, result)
                self.assertGreater(result[column], 0)

        self.assertLessEqual(result["cpu_request_namespace_used"], result["cpu_request_namespace_sum"])
        self.assertLessEqual(result["cpu_limit_namespace_used"], result["cpu_limit_namespace_sum"])
        self.assertLessEqual(result["memory_request_namespace_used"], result["memory_request_namespace_sum"])
        self.assertLessEqual(result["memory_limit_namespace_used"], result["memory_limit_namespace_sum"])

    def test_aggregate_namespace_data_yaml_resource_quota(self):
        """Test namespace quota used values from static report YAML resource_quota."""
        attributes = {
            "nodes": [
                {
                    "node_name": "worker-1",
                    "cpu_cores": 16,
                    "memory_gig": 64,
                    "namespaces": {
                        "yaml-quota-ns": {
                            "resource_quota": {
                                "cpu_request_used": 2.5,
                                "cpu_limit_used": 5.0,
                                "memory_request_used_gig": 6,
                                "memory_limit_used_gig": 12,
                            },
                            "pods": [
                                {
                                    "pod_name": "app",
                                    "cpu_request": 1,
                                    "cpu_limit": 2,
                                    "mem_request_gig": 1,
                                    "mem_limit_gig": 2,
                                }
                            ],
                        }
                    },
                }
            ]
        }
        generator = OCPGenerator(self.two_hours_ago, self.now, attributes, ros_ocp_info=True)
        result = generator._aggregate_namespace_data("yaml-quota-ns", self.two_hours_ago, self.now)

        self.assertEqual(result["cpu_request_namespace_used"], 2.5)
        self.assertEqual(result["cpu_limit_namespace_used"], 5.0)
        self.assertEqual(result["memory_request_namespace_used"], 6 * 1024 * 1024 * 1024)
        self.assertEqual(result["memory_limit_namespace_used"], 12 * 1024 * 1024 * 1024)

    def test_gpu_usage_in_report_type_to_cols(self):
        """Test that GPU usage is in the report type mapping."""
        self.assertIn(OCP_GPU_USAGE, OCP_REPORT_TYPE_TO_COLS)
        self.assertEqual(OCP_REPORT_TYPE_TO_COLS[OCP_GPU_USAGE], OCP_GPU_USAGE_COLUMNS)
        self.assertIn(OCP_GPU_USAGE, COST_OCP_REPORT_TYPE_TO_COLS)
        self.assertNotIn(OCP_GPU_USAGE, ROS_OCP_REPORT_TYPE_TO_COLS)

    def _mig_gpu_attributes(self, pod_name="mig-pod", gpu_overrides=None, mig_instance_overrides=None):
        """Minimal gpu_attributes for MIG tests. Overrides are merged into the single gpu/mig_instance."""
        gpu = {
            "gpu_model": "H100",
            "gpu_memory_capacity_mib": 81920,
            "mig_instances": [
                {
                    "mig_profile": "3g.40gb",
                    "mig_strategy": "mixed",
                },
            ],
        }
        if gpu_overrides:
            gpu.update(gpu_overrides)
        if mig_instance_overrides and gpu.get("mig_instances"):
            gpu["mig_instances"] = [{**gpu["mig_instances"][0], **mig_instance_overrides}]
        return {
            "nodes": [
                {
                    "node_name": "mig-node",
                    "cpu_cores": 16,
                    "memory_gig": 64,
                    "namespaces": {
                        "mig-namespace": {
                            "pods": [
                                {
                                    "pod_name": pod_name,
                                    "cpu_request": 4,
                                    "mem_request_gig": 16,
                                    "cpu_limit": 8,
                                    "mem_limit_gig": 32,
                                    "gpus": [gpu],
                                },
                            ]
                        }
                    },
                }
            ]
        }

    def test_gen_gpus_with_yaml_specification(self):
        """Test GPU generation with YAML specification."""
        gpu_attributes = {
            "nodes": [
                {
                    "node_name": "gpu-node",
                    "cpu_cores": 16,
                    "memory_gig": 64,
                    "namespaces": {
                        "gpu-namespace": {
                            "pods": [
                                {
                                    "pod_name": "gpu-pod",
                                    "cpu_request": 4,
                                    "mem_request_gig": 16,
                                    "cpu_limit": 8,
                                    "mem_limit_gig": 32,
                                    "gpus": [
                                        {"gpu_model": "Tesla T4", "gpu_memory_capacity_mib": 15360},
                                        {"gpu_model": "A100", "gpu_memory_capacity_mib": 40960},
                                    ],
                                }
                            ]
                        }
                    },
                }
            ]
        }
        generator = OCPGenerator(self.two_hours_ago, self.now, gpu_attributes)
        self.assertIsNotNone(generator.gpus)
        self.assertIn("gpu-pod", generator.gpus)
        pod_gpus = generator.gpus["gpu-pod"]
        self.assertEqual(len(pod_gpus), 2)
        self.assertEqual(pod_gpus[0]["gpu_model_name"], "Tesla T4")
        self.assertEqual(pod_gpus[0]["gpu_memory_capacity_mib"], 15360)
        self.assertEqual(pod_gpus[0]["gpu_vendor_name"], GPU_VENDOR)
        self.assertIn("GPU-", pod_gpus[0]["gpu_uuid"])
        self.assertEqual(pod_gpus[1]["gpu_model_name"], "A100")
        self.assertEqual(pod_gpus[1]["gpu_memory_capacity_mib"], 40960)

    def test_gen_gpus_yaml_with_mig_instances(self):
        """Test GPU generation with MIG instances from YAML."""
        generator = OCPGenerator(self.two_hours_ago, self.now, self._mig_gpu_attributes())
        self.assertIn("mig-pod", generator.gpus)
        pod_gpus = generator.gpus["mig-pod"]
        self.assertEqual(len(pod_gpus), 1)
        gpu = pod_gpus[0]
        self.assertEqual(gpu["gpu_model_name"], "H100")
        self.assertEqual(gpu["mig_profile"], "3g.40gb")
        self.assertEqual(gpu["mig_strategy"], "mixed")
        self.assertIn("GPU-", gpu["gpu_uuid"])
        self.assertIsInstance(gpu["mig_instance_id"], str)
        self.assertTrue(gpu["mig_instance_id"].startswith("MIG-"))

    def test_gen_gpus_raises_when_mig_instance_missing_required_fields(self):
        """Test that ValueError is raised when a MIG instance lacks mig_profile or mig_strategy."""
        attrs = self._mig_gpu_attributes(pod_name="incomplete-mig-pod")
        del attrs["nodes"][0]["namespaces"]["mig-namespace"]["pods"][0]["gpus"][0]["mig_instances"][0]["mig_strategy"]
        with self.assertRaises(ValueError) as ctx:
            OCPGenerator(self.two_hours_ago, self.now, attrs)
        self.assertIn("mig_profile", str(ctx.exception))
        self.assertIn("mig_strategy", str(ctx.exception))

    def test_gen_gpus_raises_when_mig_instance_id_invalid_type(self):
        """Test that ValueError is raised when mig_instance_id is not a string or integer."""
        attrs = self._mig_gpu_attributes(pod_name="invalid-mig-id-pod", mig_instance_overrides={"mig_instance_id": {}})
        with self.assertRaises(ValueError) as ctx:
            OCPGenerator(self.two_hours_ago, self.now, attrs)
        self.assertIn("invalid-mig-id-pod", str(ctx.exception))
        self.assertIn("mig_instance_id must be a string or integer", str(ctx.exception))

    def test_mig_instances_share_same_physical_gpu_uuid(self):
        """All MIG slices on one YAML gpu share gpu_uuid; mig_instance_id is unique per slice."""
        gpu = {
            "gpu_model": "A100",
            "gpu_memory_capacity_mib": 40960,
            "mig_instances": [
                {"mig_profile": "1g.5gb", "mig_strategy": "mixed"},
                {"mig_profile": "2g.10gb", "mig_strategy": "mixed"},
                {"mig_profile": "4g.40gb", "mig_strategy": "mixed"},
            ],
        }
        attrs = {
            "nodes": [
                {
                    "node_name": "mig-node",
                    "cpu_cores": 16,
                    "memory_gig": 64,
                    "namespaces": {
                        "ns": {
                            "pods": [
                                {
                                    "pod_name": "triple-mig-pod",
                                    "cpu_request": 4,
                                    "mem_request_gig": 16,
                                    "cpu_limit": 8,
                                    "mem_limit_gig": 32,
                                    "gpus": [gpu],
                                },
                            ]
                        }
                    },
                }
            ]
        }
        generator = OCPGenerator(self.two_hours_ago, self.now, attrs)
        pod_gpus = generator.gpus["triple-mig-pod"]
        self.assertEqual(len(pod_gpus), 3)
        physical_uuids = {g["gpu_uuid"] for g in pod_gpus}
        self.assertEqual(len(physical_uuids), 1)
        self.assertTrue(next(iter(physical_uuids)).startswith("GPU-"))
        mig_ids = [g["mig_instance_id"] for g in pod_gpus]
        self.assertEqual(len(set(mig_ids)), 3)
        for mid in mig_ids:
            self.assertIsInstance(mid, str)
            self.assertTrue(mid.startswith("MIG-"))

    def test_gen_hourly_gpu_usage_includes_mig_fields(self):
        """Test that GPU usage rows include MIG fields when pod has MIG instances."""
        attrs = self._mig_gpu_attributes()
        attrs["nodes"][0]["namespaces"]["mig-namespace"]["pods"][0]["pod_seconds"] = 3600
        generator = OCPGenerator(self.two_hours_ago, self.now, attrs)
        gpu_data = list(generator.generate_data(OCP_GPU_USAGE))
        self.assertGreater(len(gpu_data), 0)
        row = gpu_data[0]
        self.assertEqual(row["mig_profile"], "3g.40gb")
        self.assertEqual(row["mig_strategy"], "mixed")
        self.assertIsInstance(row["mig_instance_id"], str)
        self.assertTrue(row["mig_instance_id"].startswith("MIG-"))
        self.assertIn("GPU-", row["gpu_uuid"])

    def test_gen_gpus_random_generation(self):
        """Test random GPU generation (10% of pods)."""
        generator = OCPGenerator(self.two_hours_ago, self.now, {})
        self.assertIsNotNone(generator.gpus)
        # With random generation, some pods might have GPUs
        # We can't guarantee exactly which ones, but the structure should be correct
        for pod_name, pod_gpus in generator.gpus.items():
            self.assertIsInstance(pod_gpus, list)
            self.assertGreater(len(pod_gpus), 0)
            for gpu in pod_gpus:
                self.assertIn("gpu_uuid", gpu)
                self.assertIn("gpu_model_name", gpu)
                self.assertIn("gpu_vendor_name", gpu)
                self.assertIn("gpu_memory_capacity_mib", gpu)
                self.assertIn(gpu["gpu_model_name"], GPU_MODELS)
                self.assertEqual(gpu["gpu_vendor_name"], GPU_VENDOR)
                self.assertGreater(gpu["gpu_memory_capacity_mib"], 0)

    def test_gen_hourly_gpu_usage(self):
        """Test GPU usage data generation."""
        gpu_attributes = {
            "nodes": [
                {
                    "node_name": "gpu-node",
                    "cpu_cores": 16,
                    "memory_gig": 64,
                    "namespaces": {
                        "gpu-namespace": {
                            "pods": [
                                {
                                    "pod_name": "gpu-pod",
                                    "cpu_request": 4,
                                    "mem_request_gig": 16,
                                    "cpu_limit": 8,
                                    "mem_limit_gig": 32,
                                    "pod_seconds": 3600,
                                    "gpus": [{"gpu_model": "Tesla T4", "gpu_memory_capacity_mib": 15360}],
                                }
                            ]
                        }
                    },
                }
            ]
        }
        generator = OCPGenerator(self.two_hours_ago, self.now, gpu_attributes)
        gpu_data = list(generator.generate_data(OCP_GPU_USAGE))
        self.assertGreater(len(gpu_data), 0)
        for row in gpu_data:
            self.assertIn("node", row)
            self.assertIn("namespace", row)
            self.assertIn("pod", row)
            self.assertIn("gpu_uuid", row)
            self.assertIn("gpu_model_name", row)
            self.assertIn("gpu_vendor_name", row)
            self.assertIn("gpu_memory_capacity_mib", row)
            self.assertIn("gpu_pod_uptime", row)
            self.assertEqual(row["node"], "gpu-node")
            self.assertEqual(row["namespace"], "gpu-namespace")
            self.assertEqual(row["pod"], "gpu-pod")
            self.assertEqual(row["gpu_model_name"], "Tesla T4")
            self.assertEqual(row["gpu_memory_capacity_mib"], 15360)
            self.assertEqual(row["gpu_vendor_name"], GPU_VENDOR)
            self.assertGreater(row["gpu_pod_uptime"], 0)
            self.assertLessEqual(row["gpu_pod_uptime"], 3600)

    def test_update_gpu_data(self):
        """Test GPU data row update."""
        generator = OCPGenerator(self.two_hours_ago, self.now, {})
        row = generator._init_data_row(self.two_hours_ago, self.now, report_type=OCP_GPU_USAGE)
        kwargs = {
            "node": "test-node",
            "namespace": "test-namespace",
            "pod": "test-pod",
            "gpu_uuid": "GPU-test-uuid",
            "gpu_model_name": "Tesla T4",
            "gpu_vendor_name": GPU_VENDOR,
            "gpu_memory_capacity_mib": 15360,
            "gpu_pod_uptime": 3000.123456,
            "mig_instance_id": "MIG-partition-1",
            "mig_profile": "3g.40gb",
            "mig_strategy": "mixed",
        }
        updated_row = generator._update_gpu_data(row, self.two_hours_ago, self.now, **kwargs)
        self.assertEqual(updated_row["node"], "test-node")
        self.assertEqual(updated_row["namespace"], "test-namespace")
        self.assertEqual(updated_row["pod"], "test-pod")
        self.assertEqual(updated_row["gpu_uuid"], "GPU-test-uuid")
        self.assertEqual(updated_row["gpu_model_name"], "Tesla T4")
        self.assertEqual(updated_row["gpu_vendor_name"], GPU_VENDOR)
        self.assertEqual(updated_row["gpu_memory_capacity_mib"], 15360)
        self.assertEqual(updated_row["gpu_pod_uptime"], 3000.123456)
        self.assertEqual(updated_row["mig_instance_id"], "MIG-partition-1")
        self.assertEqual(updated_row["mig_profile"], "3g.40gb")
        self.assertEqual(updated_row["mig_strategy"], "mixed")

    def test_gpu_usage_with_multiple_gpus_per_pod(self):
        """Test that multiple GPUs per pod generate separate rows."""
        gpu_attributes = {
            "nodes": [
                {
                    "node_name": "multi-gpu-node",
                    "cpu_cores": 32,
                    "memory_gig": 256,
                    "namespaces": {
                        "ml-namespace": {
                            "pods": [
                                {
                                    "pod_name": "multi-gpu-pod",
                                    "cpu_request": 16,
                                    "mem_request_gig": 128,
                                    "cpu_limit": 32,
                                    "mem_limit_gig": 256,
                                    "gpus": [
                                        {"gpu_model": "H100", "gpu_memory_capacity_mib": 81920},
                                        {"gpu_model": "H100", "gpu_memory_capacity_mib": 81920},
                                        {"gpu_model": "H100", "gpu_memory_capacity_mib": 81920},
                                        {"gpu_model": "H100", "gpu_memory_capacity_mib": 81920},
                                    ],
                                }
                            ]
                        }
                    },
                }
            ]
        }
        generator = OCPGenerator(self.two_hours_ago, self.now, gpu_attributes)
        gpu_data = list(generator.generate_data(OCP_GPU_USAGE))
        # Should generate rows for each GPU * number of hours
        num_hours = len(generator.hours)
        expected_rows = 4 * num_hours  # 4 GPUs
        self.assertEqual(len(gpu_data), expected_rows)
        # All rows should be for the same pod but different GPUs
        pod_names = set(row["pod"] for row in gpu_data)
        self.assertEqual(len(pod_names), 1)
        self.assertEqual(pod_names.pop(), "multi-gpu-pod")
        # Check that we have 4 unique GPU UUIDs
        gpu_uuids = set(row["gpu_uuid"] for row in gpu_data)
        self.assertEqual(len(gpu_uuids), 4)
        # Check that all GPUs for the same pod in the same hour have the same uptime
        uptimes_by_hour = {}
        for row in gpu_data:
            hour_key = (row["interval_start"], row["pod"])
            if hour_key not in uptimes_by_hour:
                uptimes_by_hour[hour_key] = []
            uptimes_by_hour[hour_key].append(row["gpu_pod_uptime"])
        # All GPUs in the same hour should have identical uptime
        for hour_key, uptimes in uptimes_by_hour.items():
            unique_uptimes = set(uptimes)
            self.assertEqual(
                len(unique_uptimes),
                1,
                f"Expected all GPUs in hour {hour_key} to have same uptime, got {uptimes}",
            )

    def test_gpu_pod_uptime_matches_pod_seconds(self):
        """Test that gpu_pod_uptime equals pod_seconds when specified in YAML."""
        # Define specific pod_seconds value
        specific_pod_seconds = 2500
        gpu_attributes = {
            "nodes": [
                {
                    "node_name": "gpu-node-with-uptime",
                    "cpu_cores": 16,
                    "memory_gig": 128,
                    "namespaces": {
                        "ai-training": {
                            "pods": [
                                {
                                    "pod_name": "training-pod-with-uptime",
                                    "cpu_request": 8,
                                    "mem_request_gig": 64,
                                    "cpu_limit": 16,
                                    "mem_limit_gig": 128,
                                    "pod_seconds": specific_pod_seconds,  # Specify exact uptime
                                    "gpus": [
                                        {"gpu_model": "A100", "gpu_memory_capacity_mib": 40960},
                                        {"gpu_model": "A100", "gpu_memory_capacity_mib": 40960},
                                        {"gpu_model": "H100", "gpu_memory_capacity_mib": 81920},
                                    ],
                                }
                            ]
                        }
                    },
                }
            ]
        }
        generator = OCPGenerator(self.two_hours_ago, self.now, gpu_attributes)
        gpu_data = list(generator.generate_data(OCP_GPU_USAGE))
        # All GPU rows should have gpu_pod_uptime equal to pod_seconds
        for row in gpu_data:
            self.assertEqual(
                row["gpu_pod_uptime"],
                specific_pod_seconds,
                f"Expected gpu_pod_uptime to be {specific_pod_seconds}, got {row['gpu_pod_uptime']}",
            )
        # Verify all GPUs have the same value
        uptimes = [row["gpu_pod_uptime"] for row in gpu_data]
        unique_uptimes = set(uptimes)
        self.assertEqual(len(unique_uptimes), 1, f"Expected all GPUs to have same uptime, got {unique_uptimes}")
        self.assertEqual(unique_uptimes.pop(), specific_pod_seconds)

    def test_ros_usage_column_includes_oom_count(self):
        """Test that OCP_ROS_USAGE_COLUMN includes the oom_count field."""
        self.assertIn("oom_count", OCP_ROS_USAGE_COLUMN)

    def test_ros_usage_column_oom_count_position(self):
        """Test that oom_count follows memory_rss_usage_container_sum in the ROS CSV header."""
        idx = OCP_ROS_USAGE_COLUMN.index("oom_count")
        self.assertEqual(OCP_ROS_USAGE_COLUMN[idx - 1], "memory_rss_usage_container_sum")

    def test_ros_usage_column_node_metadata(self):
        """ROS container CSV includes pod capacity and MachineSet name for node digests."""
        self.assertIn("node_capacity_pods", OCP_ROS_USAGE_COLUMN)
        self.assertIn("machineset_name", OCP_ROS_USAGE_COLUMN)
        mem_idx = OCP_ROS_USAGE_COLUMN.index("node_capacity_memory_bytes")
        self.assertEqual(OCP_ROS_USAGE_COLUMN[mem_idx + 1], "node_capacity_pods")
        self.assertEqual(OCP_ROS_USAGE_COLUMN[mem_idx + 2], "machineset_name")

    def test_machineset_name_from_node(self):
        """MachineSet name is derived from node hostname prefix."""
        self.assertEqual(machineset_name_from_node("worker-0"), "worker")
        self.assertEqual(machineset_name_from_node("infra-1"), "infra")
        self.assertEqual(machineset_name_from_node("worker-0.example.com"), "worker")

    def test_node_capacity_pods_for_node(self):
        """Large nodes get higher pod capacity than standard workers."""
        self.assertEqual(node_capacity_pods_for_node(4, 16 * GIGABYTE), 110)
        self.assertEqual(node_capacity_pods_for_node(32, 256 * GIGABYTE), 250)

    def test_ros_data_contains_node_metadata(self):
        """Generated ROS pod rows include machineset_name and node_capacity_pods."""
        generator = OCPGenerator(self.two_hours_ago, self.now, {}, ros_ocp_info=True)
        for pod_data in generator.ros_data.values():
            self.assertIn("machineset_name", pod_data)
            self.assertIn("node_capacity_pods", pod_data)
            self.assertGreater(pod_data["node_capacity_pods"], 0)

    def test_ros_data_contains_oom_count(self):
        """Test that generated ROS pod data includes oom_count with valid values."""
        random.seed(42)
        generator = OCPGenerator(self.two_hours_ago, self.now, {}, ros_ocp_info=True)

        has_zero = False
        for pod_key, pod_data in generator.ros_data.items():
            oom_val = pod_data.get("oom_count")
            self.assertIsNotNone(oom_val, f"pod {pod_key} should have oom_count")
            self.assertIsInstance(oom_val, int)
            self.assertGreaterEqual(oom_val, 0)
            self.assertLessEqual(oom_val, 3)
            if oom_val == 0:
                has_zero = True

        self.assertTrue(has_zero, "at least one pod should have oom_count=0")

    def test_ros_data_yaml_driven_contains_oom_count(self):
        """Test that YAML-driven ROS pod data includes oom_count."""
        random.seed(42)
        attributes = {
            "nodes": [
                {
                    "node_name": "test-node",
                    "cpu_cores": 4,
                    "memory_gig": 16,
                    "namespaces": {
                        "test-ns": {
                            "pods": [
                                {
                                    "pod_name": "test-pod",
                                    "cpu_request": 1,
                                    "mem_request_gig": 2,
                                    "cpu_limit": 2,
                                    "mem_limit_gig": 4,
                                }
                            ]
                        }
                    },
                }
            ]
        }
        generator = OCPGenerator(self.two_hours_ago, self.now, attributes, ros_ocp_info=True)

        for pod_key, pod_data in generator.ros_data.items():
            oom_val = pod_data.get("oom_count")
            self.assertIsNotNone(oom_val, f"YAML-driven pod {pod_key} should have oom_count")
            self.assertIsInstance(oom_val, int)
            self.assertGreaterEqual(oom_val, 0)
            self.assertLessEqual(oom_val, 3)

    def test_ros_usage_column_includes_workload_pod_count(self):
        """Test that OCP_ROS_USAGE_COLUMN includes the workload_pod_count field."""
        self.assertIn("workload_pod_count", OCP_ROS_USAGE_COLUMN)

    def test_ros_usage_column_workload_pod_count_position(self):
        """Test that workload_pod_count follows oom_count in the ROS CSV header."""
        idx = OCP_ROS_USAGE_COLUMN.index("workload_pod_count")
        self.assertEqual(OCP_ROS_USAGE_COLUMN[idx - 1], "oom_count")

    def test_ros_data_contains_workload_pod_count(self):
        """Test that generated ROS pod data includes workload_pod_count with valid values."""
        random.seed(42)
        generator = OCPGenerator(self.two_hours_ago, self.now, {}, ros_ocp_info=True)

        for pod_key, pod_data in generator.ros_data.items():
            wpc = pod_data.get("workload_pod_count")
            self.assertIsNotNone(wpc, f"pod {pod_key} should have workload_pod_count")
            self.assertIsInstance(wpc, int)
            self.assertGreaterEqual(wpc, 1)
            self.assertLessEqual(wpc, 5)

    def test_ros_data_yaml_driven_contains_workload_pod_count(self):
        """Test that YAML-driven ROS pod data includes workload_pod_count."""
        attributes = {
            "nodes": [
                {
                    "node_name": "test-node",
                    "cpu_cores": 4,
                    "memory_gig": 16,
                    "namespaces": {
                        "test-ns": {
                            "pods": [
                                {
                                    "pod_name": "test-pod",
                                    "cpu_request": 1,
                                    "mem_request_gig": 2,
                                    "cpu_limit": 2,
                                    "mem_limit_gig": 4,
                                }
                            ]
                        }
                    },
                }
            ]
        }
        generator = OCPGenerator(self.two_hours_ago, self.now, attributes, ros_ocp_info=True)

        for pod_key, pod_data in generator.ros_data.items():
            wpc = pod_data.get("workload_pod_count")
            self.assertIsNotNone(wpc, f"YAML-driven pod {pod_key} should have workload_pod_count")
            self.assertIsInstance(wpc, int)
            self.assertGreaterEqual(wpc, 1)
            self.assertLessEqual(wpc, 5)

    def test_ros_data_yaml_explicit_replica_count(self):
        """Test that YAML replica_count is respected as workload_pod_count."""
        attributes = {
            "nodes": [
                {
                    "node_name": "test-node",
                    "cpu_cores": 4,
                    "memory_gig": 16,
                    "namespaces": {
                        "test-ns": {
                            "pods": [
                                {
                                    "pod_name": "api-server",
                                    "cpu_request": 1,
                                    "mem_request_gig": 2,
                                    "cpu_limit": 2,
                                    "mem_limit_gig": 4,
                                    "replica_count": 7,
                                }
                            ]
                        }
                    },
                }
            ]
        }
        generator = OCPGenerator(self.two_hours_ago, self.now, attributes, ros_ocp_info=True)

        found = False
        for pod_key, pod_data in generator.ros_data.items():
            if pod_data.get("pod") == "api-server":
                self.assertEqual(pod_data["workload_pod_count"], 7)
                found = True
        self.assertTrue(found, "api-server pod not found in ros_data")

    def test_ros_usage_column_includes_gpu_columns(self):
        """Test that OCP_ROS_USAGE_COLUMN includes all 14 GPU profiling columns."""
        gpu_columns = [
            "accelerator_model_name",
            "accelerator_profile_name",
            "accelerator_frame_buffer_usage_min",
            "accelerator_frame_buffer_usage_max",
            "accelerator_frame_buffer_usage_avg",
            "tensor_pipe_active_min",
            "tensor_pipe_active_max",
            "tensor_pipe_active_avg",
            "dram_active_min",
            "dram_active_max",
            "dram_active_avg",
            "sm_active_min",
            "sm_active_max",
            "sm_active_avg",
        ]
        for col in gpu_columns:
            with self.subTest(column=col):
                self.assertIn(col, OCP_ROS_USAGE_COLUMN)

    def test_ros_usage_column_gpu_columns_after_replica_columns(self):
        """Test that GPU columns appear after available_replicas in the ROS CSV header."""
        avail_idx = OCP_ROS_USAGE_COLUMN.index("available_replicas")
        model_idx = OCP_ROS_USAGE_COLUMN.index("accelerator_model_name")
        self.assertEqual(model_idx, avail_idx + 1)

    def test_ros_data_gpu_pod_has_gpu_metrics(self):
        """Test that ROS data for GPU-equipped pods includes GPU profiling metrics."""
        attributes = {
            "nodes": [
                {
                    "node_name": "gpu-node",
                    "cpu_cores": 16,
                    "memory_gig": 64,
                    "namespaces": {
                        "ml-ns": {
                            "pods": [
                                {
                                    "pod_name": "training-pod",
                                    "cpu_request": 4,
                                    "mem_request_gig": 16,
                                    "cpu_limit": 8,
                                    "mem_limit_gig": 32,
                                    "gpus": [
                                        {"gpu_model": "A100", "gpu_memory_capacity_mib": 40960},
                                    ],
                                }
                            ]
                        }
                    },
                }
            ]
        }
        generator = OCPGenerator(self.two_hours_ago, self.now, attributes, ros_ocp_info=True)

        found = False
        for pod_key, pod_data in generator.ros_data.items():
            if pod_data.get("pod") == "training-pod":
                found = True
                self.assertEqual(pod_data["accelerator_model_name"], "A100")
                self.assertIsInstance(pod_data["accelerator_frame_buffer_usage_avg"], float)
                self.assertGreater(pod_data["accelerator_frame_buffer_usage_avg"], 0)
                self.assertIsInstance(pod_data["tensor_pipe_active_avg"], float)
                self.assertGreaterEqual(pod_data["tensor_pipe_active_avg"], 0)
                self.assertLessEqual(pod_data["tensor_pipe_active_avg"], 1.0)
                self.assertIsInstance(pod_data["dram_active_avg"], float)
                self.assertIsInstance(pod_data["sm_active_avg"], float)
        self.assertTrue(found, "training-pod not found in ros_data")

    def test_ros_data_non_gpu_pod_has_empty_gpu_metrics(self):
        """Test that ROS data for non-GPU pods has empty GPU columns."""
        attributes = {
            "nodes": [
                {
                    "node_name": "cpu-node",
                    "cpu_cores": 4,
                    "memory_gig": 16,
                    "namespaces": {
                        "web-ns": {
                            "pods": [
                                {
                                    "pod_name": "web-server",
                                    "cpu_request": 1,
                                    "mem_request_gig": 2,
                                    "cpu_limit": 2,
                                    "mem_limit_gig": 4,
                                }
                            ]
                        }
                    },
                }
            ]
        }
        generator = OCPGenerator(self.two_hours_ago, self.now, attributes, ros_ocp_info=True)

        found = False
        for pod_key, pod_data in generator.ros_data.items():
            if pod_data.get("pod") == "web-server":
                found = True
                self.assertEqual(pod_data["accelerator_model_name"], "")
                self.assertEqual(pod_data["accelerator_profile_name"], "")
                self.assertEqual(pod_data["tensor_pipe_active_avg"], "")
                self.assertEqual(pod_data["accelerator_frame_buffer_usage_avg"], "")
        self.assertTrue(found, "web-server not found in ros_data")

    def test_ros_data_tier2_gpu_no_profiling_metrics(self):
        """Test that Tier 2 GPUs (V100) have FB usage but empty PROF_ metrics."""
        attributes = {
            "nodes": [
                {
                    "node_name": "v100-node",
                    "cpu_cores": 16,
                    "memory_gig": 64,
                    "namespaces": {
                        "legacy-ns": {
                            "pods": [
                                {
                                    "pod_name": "legacy-ml-pod",
                                    "cpu_request": 4,
                                    "mem_request_gig": 16,
                                    "cpu_limit": 8,
                                    "mem_limit_gig": 32,
                                    "gpus": [
                                        {"gpu_model": "V100", "gpu_memory_capacity_mib": 32768},
                                    ],
                                }
                            ]
                        }
                    },
                }
            ]
        }
        generator = OCPGenerator(self.two_hours_ago, self.now, attributes, ros_ocp_info=True)

        found = False
        for pod_key, pod_data in generator.ros_data.items():
            if pod_data.get("pod") == "legacy-ml-pod":
                found = True
                self.assertEqual(pod_data["accelerator_model_name"], "V100")
                self.assertIsInstance(pod_data["accelerator_frame_buffer_usage_avg"], float)
                self.assertGreater(pod_data["accelerator_frame_buffer_usage_avg"], 0)
                self.assertEqual(pod_data["tensor_pipe_active_avg"], "")
                self.assertEqual(pod_data["dram_active_avg"], "")
                self.assertEqual(pod_data["sm_active_avg"], "")
        self.assertTrue(found, "legacy-ml-pod not found in ros_data")

    def test_ros_data_mig_gpu_has_profile_name(self):
        """Test that MIG-equipped GPUs include the profile name in ROS data."""
        attributes = {
            "nodes": [
                {
                    "node_name": "mig-node",
                    "cpu_cores": 32,
                    "memory_gig": 256,
                    "namespaces": {
                        "mig-ns": {
                            "pods": [
                                {
                                    "pod_name": "mig-workload",
                                    "cpu_request": 8,
                                    "mem_request_gig": 64,
                                    "cpu_limit": 16,
                                    "mem_limit_gig": 128,
                                    "gpus": [
                                        {
                                            "gpu_model": "A100",
                                            "gpu_memory_capacity_mib": 40960,
                                            "mig_instances": [
                                                {"mig_profile": "3g.20gb", "mig_strategy": "mixed"},
                                            ],
                                        },
                                    ],
                                }
                            ]
                        }
                    },
                }
            ]
        }
        generator = OCPGenerator(self.two_hours_ago, self.now, attributes, ros_ocp_info=True)

        found = False
        for pod_key, pod_data in generator.ros_data.items():
            if pod_data.get("pod") == "mig-workload":
                found = True
                self.assertEqual(pod_data["accelerator_model_name"], "A100")
                self.assertEqual(pod_data["accelerator_profile_name"], "3g.20gb")
        self.assertTrue(found, "mig-workload not found in ros_data")

    def test_ros_data_gpu_idle_override(self):
        """Test that YAML metric overrides produce idle-like GPU metrics."""
        attributes = {
            "nodes": [
                {
                    "node_name": "gpu-node",
                    "cpu_cores": 16,
                    "memory_gig": 64,
                    "namespaces": {
                        "ml-ns": {
                            "pods": [
                                {
                                    "pod_name": "idle-gpu-pod",
                                    "cpu_request": 1,
                                    "mem_request_gig": 4,
                                    "cpu_limit": 2,
                                    "mem_limit_gig": 8,
                                    "gpus": [
                                        {
                                            "gpu_model": "A100",
                                            "gpu_memory_capacity_mib": 40960,
                                            "sm_active_avg": 0.01,
                                            "tensor_pipe_active_avg": 0.005,
                                            "dram_active_avg": 0.02,
                                            "fb_usage_avg": 50.0,
                                        },
                                    ],
                                }
                            ]
                        }
                    },
                }
            ]
        }
        generator = OCPGenerator(self.two_hours_ago, self.now, attributes, ros_ocp_info=True)

        found = False
        for pod_key, pod_data in generator.ros_data.items():
            if pod_data.get("pod") == "idle-gpu-pod":
                found = True
                self.assertEqual(pod_data["accelerator_model_name"], "A100")
                self.assertAlmostEqual(pod_data["sm_active_avg"], 0.01)
                self.assertAlmostEqual(pod_data["tensor_pipe_active_avg"], 0.005)
                self.assertAlmostEqual(pod_data["dram_active_avg"], 0.02)
                self.assertAlmostEqual(pod_data["accelerator_frame_buffer_usage_avg"], 50.0)
                self.assertLessEqual(pod_data["sm_active_max"], 1.0)
                self.assertGreaterEqual(pod_data["sm_active_min"], 0.0)
        self.assertTrue(found, "idle-gpu-pod not found in ros_data")

    def test_ros_data_gpu_mig_candidate_override(self):
        """Test metric overrides for a MIG-candidate GPU (active but low FB)."""
        attributes = {
            "nodes": [
                {
                    "node_name": "gpu-node",
                    "cpu_cores": 16,
                    "memory_gig": 64,
                    "namespaces": {
                        "ml-ns": {
                            "pods": [
                                {
                                    "pod_name": "mig-candidate-pod",
                                    "cpu_request": 4,
                                    "mem_request_gig": 16,
                                    "cpu_limit": 8,
                                    "mem_limit_gig": 32,
                                    "gpus": [
                                        {
                                            "gpu_model": "A100",
                                            "gpu_memory_capacity_mib": 81920,
                                            "sm_active_avg": 0.25,
                                            "tensor_pipe_active_avg": 0.10,
                                            "dram_active_avg": 0.15,
                                            "fb_usage_avg": 3000.0,
                                        },
                                    ],
                                }
                            ]
                        }
                    },
                }
            ]
        }
        generator = OCPGenerator(self.two_hours_ago, self.now, attributes, ros_ocp_info=True)

        found = False
        for pod_key, pod_data in generator.ros_data.items():
            if pod_data.get("pod") == "mig-candidate-pod":
                found = True
                self.assertEqual(pod_data["accelerator_model_name"], "A100")
                self.assertAlmostEqual(pod_data["sm_active_avg"], 0.25)
                self.assertAlmostEqual(pod_data["tensor_pipe_active_avg"], 0.10)
                self.assertAlmostEqual(pod_data["dram_active_avg"], 0.15)
                self.assertAlmostEqual(pod_data["accelerator_frame_buffer_usage_avg"], 3000.0)
        self.assertTrue(found, "mig-candidate-pod not found in ros_data")

    def test_snapshot_inventory_generated_with_ros_ocp_info(self):
        """Test that OCPGenerator with ros_ocp_info=True produces OCP_SNAPSHOT_INVENTORY data."""
        from nise.generators.ocp.ocp_generator import OCP_SNAPSHOT_INVENTORY

        generator = OCPGenerator(self.two_hours_ago, self.now, {}, ros_ocp_info=True)

        self.assertIn(OCP_SNAPSHOT_INVENTORY, generator.ocp_report_generation)
        self.assertTrue(hasattr(generator, "snapshots"))
        self.assertIsInstance(generator.snapshots, list)
        self.assertGreater(len(generator.snapshots), 0)

    def test_snapshot_inventory_not_generated_without_ros_ocp_info(self):
        """Test that OCPGenerator without ros_ocp_info does NOT produce snapshot data."""
        from nise.generators.ocp.ocp_generator import OCP_SNAPSHOT_INVENTORY

        generator = OCPGenerator(self.two_hours_ago, self.now, {})

        self.assertNotIn(OCP_SNAPSHOT_INVENTORY, generator.ocp_report_generation)
        self.assertFalse(hasattr(generator, "snapshots"))

    def test_snapshot_inventory_csv_columns(self):
        """Test that snapshot inventory output CSV has correct column count and header names."""
        from nise.generators.ocp.ocp_generator import OCP_SNAPSHOT_INVENTORY, OCP_SNAPSHOT_INVENTORY_COLUMNS

        generator = OCPGenerator(self.two_hours_ago, self.now, {}, ros_ocp_info=True)

        rows = list(generator.generate_data(report_type=OCP_SNAPSHOT_INVENTORY))
        self.assertGreater(len(rows), 0)

        first_row = rows[0]
        for col in OCP_SNAPSHOT_INVENTORY_COLUMNS:
            self.assertIn(col, first_row, f"Missing column '{col}' in snapshot inventory row")

        self.assertEqual(len(first_row), len(OCP_SNAPSHOT_INVENTORY_COLUMNS))

    def test_snapshot_inventory_row_content(self):
        """Test that snapshot inventory rows contain valid data."""
        from nise.generators.ocp.ocp_generator import OCP_SNAPSHOT_INVENTORY

        generator = OCPGenerator(self.two_hours_ago, self.now, {}, ros_ocp_info=True)

        rows = list(generator.generate_data(report_type=OCP_SNAPSHOT_INVENTORY))
        for row in rows:
            self.assertIn(row["ready_to_use"], ("true", "false"))
            self.assertIn(row["source_pvc_exists"], ("true", "false"))
            self.assertIsInstance(row["restore_size_bytes"], int)
            self.assertGreater(row["restore_size_bytes"], 0)
            self.assertIsInstance(row["restored_pvc_count"], int)
            self.assertGreaterEqual(row["restored_pvc_count"], 0)
            self.assertTrue(len(row["namespace"]) > 0)
            self.assertTrue(len(row["snapshot_name"]) > 0)

    def test_snapshot_inventory_categorized_as_ros_report(self):
        """Test that OCP_SNAPSHOT_INVENTORY is in ROS_OCP_REPORT_TYPE_TO_COLS."""
        from nise.generators.ocp.ocp_generator import (
            OCP_SNAPSHOT_INVENTORY,
            OCP_SNAPSHOT_INVENTORY_COLUMNS,
            ROS_OCP_REPORT_TYPE_TO_COLS,
        )

        self.assertIn(OCP_SNAPSHOT_INVENTORY, ROS_OCP_REPORT_TYPE_TO_COLS)
        self.assertEqual(
            ROS_OCP_REPORT_TYPE_TO_COLS[OCP_SNAPSHOT_INVENTORY],
            OCP_SNAPSHOT_INVENTORY_COLUMNS,
        )

    def test_gen_snapshots_includes_stale_entry(self):
        """Test that _gen_snapshots always includes at least one explicitly stale snapshot."""
        generator = OCPGenerator(self.two_hours_ago, self.now, {}, ros_ocp_info=True)

        stale_snaps = [s for s in generator.snapshots if s["snapshot_name"] == "legacy-backup-never-restored"]
        self.assertEqual(len(stale_snaps), 1)
        stale = stale_snaps[0]
        self.assertEqual(stale["source_pvc_name"], "data-pvc-legacy")
        self.assertEqual(stale["restored_pvc_count"], 0)

    def test_static_yaml_snapshot_support(self):
        """Test that snapshots from static YAML produce deterministic output."""
        from nise.generators.ocp.ocp_generator import OCP_SNAPSHOT_INVENTORY

        attributes = {
            "nodes": [
                {
                    "node": "static-node-1",
                    "node_name": "worker-0",
                    "cpu_cores": 4,
                    "memory_gig": 16,
                    "namespaces": {
                        "prod": {
                            "pods": [
                                {
                                    "pod": "pod-1",
                                    "pod_name": "web",
                                    "cpu_request": 1,
                                    "mem_request_gig": 2,
                                    "cpu_limit": 2,
                                    "mem_limit_gig": 4,
                                }
                            ],
                            "volumes": [
                                {
                                    "volume_name": "vol-1",
                                    "volume_request_gig": 50,
                                    "volume_claims": [
                                        {"volume_claim_name": "data-pvc", "pod_name": "web", "capacity_gig": 50}
                                    ],
                                }
                            ],
                        }
                    },
                }
            ],
            "snapshots": [
                {
                    "snapshot_name": "db-daily-backup",
                    "namespace": "prod",
                    "source_pvc_name": "postgres-data",
                    "storageclass": "gp3",
                    "creation_days_ago": 120,
                    "source_pvc_exists": True,
                    "restored_pvc_count": 0,
                    "labels": {"velero.io/backup-name": "daily-schedule"},
                },
                {
                    "snapshot_name": "orphan-snap",
                    "namespace": "prod",
                    "source_pvc_name": "",
                    "source_pvc_exists": False,
                    "creation_days_ago": 60,
                },
            ],
        }

        generator = OCPGenerator(self.two_hours_ago, self.now, attributes, ros_ocp_info=True)

        self.assertEqual(len(generator.snapshots), 2)
        self.assertEqual(generator.snapshots[0]["snapshot_name"], "db-daily-backup")
        self.assertEqual(generator.snapshots[0]["namespace"], "prod")
        self.assertEqual(generator.snapshots[0]["source_pvc_name"], "postgres-data")
        self.assertEqual(generator.snapshots[0]["storageclass"], "gp3")
        self.assertEqual(generator.snapshots[0]["restored_pvc_count"], 0)
        self.assertEqual(generator.snapshots[0]["labels"], {"velero.io/backup-name": "daily-schedule"})
        self.assertEqual(generator.snapshots[0]["source_pvc_exists"], "true")

        self.assertEqual(generator.snapshots[1]["snapshot_name"], "orphan-snap")
        self.assertEqual(generator.snapshots[1]["source_pvc_exists"], "false")
        self.assertEqual(generator.snapshots[1]["source_pvc_name"], "")

        rows = list(generator.generate_data(report_type=OCP_SNAPSHOT_INVENTORY))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["snapshot_name"], "db-daily-backup")
        self.assertEqual(rows[1]["snapshot_name"], "orphan-snap")


class GenRosGpuMetricsTest(TestCase):
    """Tests for the _gen_ros_gpu_metrics function with overrides."""

    def test_tier1_no_overrides_generates_random(self):
        m = _gen_ros_gpu_metrics("A100", 40960)
        self.assertEqual(m["accelerator_model_name"], "A100")
        self.assertIsInstance(m["sm_active_avg"], float)
        self.assertGreaterEqual(m["sm_active_avg"], 0.05)
        self.assertLessEqual(m["sm_active_avg"], 0.90)

    def test_tier1_idle_overrides(self):
        overrides = {
            "sm_active_avg": 0.01,
            "tensor_pipe_active_avg": 0.005,
            "dram_active_avg": 0.02,
            "fb_usage_avg": 50.0,
        }
        m = _gen_ros_gpu_metrics("A100", 40960, overrides=overrides)
        self.assertAlmostEqual(m["sm_active_avg"], 0.01)
        self.assertAlmostEqual(m["tensor_pipe_active_avg"], 0.005)
        self.assertAlmostEqual(m["dram_active_avg"], 0.02)
        self.assertAlmostEqual(m["accelerator_frame_buffer_usage_avg"], 50.0)
        self.assertLessEqual(m["sm_active_min"], 0.01)
        self.assertGreaterEqual(m["sm_active_min"], 0.0)

    def test_tier2_overrides_only_fb(self):
        overrides = {"fb_usage_avg": 100.0}
        m = _gen_ros_gpu_metrics("V100", 16384, overrides=overrides)
        self.assertAlmostEqual(m["accelerator_frame_buffer_usage_avg"], 100.0)
        self.assertEqual(m["sm_active_avg"], "")

    def test_partial_overrides_rest_random(self):
        overrides = {"sm_active_avg": 0.80}
        m = _gen_ros_gpu_metrics("A100", 40960, overrides=overrides)
        self.assertAlmostEqual(m["sm_active_avg"], 0.80)
        self.assertIsInstance(m["tensor_pipe_active_avg"], float)
        self.assertIsInstance(m["dram_active_avg"], float)

    def test_mig_profile_with_overrides(self):
        overrides = {"sm_active_avg": 0.50, "fb_usage_avg": 5000.0}
        m = _gen_ros_gpu_metrics("A100", 81920, mig_profile="3g.40gb", overrides=overrides)
        self.assertEqual(m["accelerator_profile_name"], "3g.40gb")
        self.assertAlmostEqual(m["sm_active_avg"], 0.50)
        self.assertAlmostEqual(m["accelerator_frame_buffer_usage_avg"], 5000.0)


class ResolveMigPartitionIdTest(TestCase):
    """Tests for OCPGenerator._resolve_mig_partition_id."""

    def test_none_uses_stable_uuid_from_mig_name(self):
        mig_name = "nise.ocp.mig.node-a.pod-b.0.1"
        expected = f"MIG-{uuid5(NAMESPACE_DNS, mig_name)}"
        result = OCPGenerator._resolve_mig_partition_id("pod-b", mig_name, None)
        self.assertEqual(result, expected)
        self.assertTrue(result.startswith("MIG-"))

    def test_none_same_mig_name_same_id(self):
        mig_name = "nise.ocp.mig.n.p.0.0"
        a = OCPGenerator._resolve_mig_partition_id("p", mig_name, None)
        b = OCPGenerator._resolve_mig_partition_id("p", mig_name, None)
        self.assertEqual(a, b)

    def test_none_different_mig_name_different_id(self):
        a = OCPGenerator._resolve_mig_partition_id("p", "nise.ocp.mig.n.p.0.0", None)
        b = OCPGenerator._resolve_mig_partition_id("p", "nise.ocp.mig.n.p.0.1", None)
        self.assertNotEqual(a, b)

    def test_string_returned_unchanged(self):
        self.assertEqual(
            OCPGenerator._resolve_mig_partition_id("pod", "mig", "MIG-abc-123"),
            "MIG-abc-123",
        )
        self.assertEqual(
            OCPGenerator._resolve_mig_partition_id("pod", "mig", "custom-partition"),
            "custom-partition",
        )

    def test_int_prefixed_with_mig(self):
        self.assertEqual(OCPGenerator._resolve_mig_partition_id("p", "m", 7), "MIG-7")
        self.assertEqual(OCPGenerator._resolve_mig_partition_id("p", "m", 0), "MIG-0")

    def test_coerces_numeric_non_int_via_int(self):
        self.assertEqual(OCPGenerator._resolve_mig_partition_id("p", "m", 3.9), "MIG-3")

    def test_invalid_type_raises_value_error(self):
        with self.assertRaises(ValueError) as ctx:
            OCPGenerator._resolve_mig_partition_id("my-pod", "m", {})
        self.assertIn("my-pod", str(ctx.exception))
        self.assertIn("mig_instance_id must be a string or integer", str(ctx.exception))
        self.assertIn("dict", str(ctx.exception))

    def test_invalid_type_list(self):
        with self.assertRaises(ValueError):
            OCPGenerator._resolve_mig_partition_id("p", "m", [])
