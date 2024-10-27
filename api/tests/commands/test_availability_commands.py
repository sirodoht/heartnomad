from datetime import datetime

from django.test import TestCase

from api.commands.capacities import DeleteCapacityChange
from core.factories import ResourceFactory, UserFactory
from core.models import CapacityChange


class DeleteCapacityChangeTestCase(TestCase):
    def setUp(self):
        self.user = UserFactory()
        self.resource = ResourceFactory()
        self.resource.location.house_admins.add(self.user)

    def expect_deleted_capacities(self, expected_ids, remaining=0):
        self.assertTrue(self.command.execute())
        self.assertEqual(CapacityChange.objects.count(), remaining)
        expected_data = {"data": {"deleted": {"capacities": expected_ids}}}
        self.assertEqual(self.command.result().serialize(), expected_data)

    def test_that_command_from_non_house_admin_fails(self):
        capacity = CapacityChange.objects.create(
            start_date=datetime.date(4016, 1, 13), resource=self.resource, quantity=2
        )
        non_admin = UserFactory(username="samwise")
        self.command = DeleteCapacityChange(non_admin, capacity=capacity)
        self.assertFalse(self.command.execute())

    def test_cant_delete_capacity_in_the_past(self):
        capacity = CapacityChange.objects.create(
            start_date=datetime.date(1016, 1, 13), resource=self.resource, quantity=2
        )

        command = DeleteCapacityChange(self.user, capacity=capacity)
        self.assertFalse(command.execute())
        self.assertEqual(CapacityChange.objects.count(), 1)
        expected_data = {
            "errors": {"start_date": ["The start date must not be in the past"]}
        }
        self.assertEqual(command.result().serialize(), expected_data)

    def test_can_delete_capacity_in_the_future(self):
        capacity = CapacityChange.objects.create(
            start_date=datetime.date(4016, 1, 13), resource=self.resource, quantity=2
        )
        self.command = DeleteCapacityChange(self.user, capacity=capacity)
        self.expect_deleted_capacities([capacity.pk])

    def test_deleting_capacity_also_deletes_next_one_if_it_is_the_same_as_previous(
        self,
    ):
        CapacityChange.objects.create(
            start_date=datetime.date(4016, 1, 12), resource=self.resource, quantity=3
        )
        capacity = CapacityChange.objects.create(
            start_date=datetime.date(4016, 1, 13), resource=self.resource, quantity=2
        )
        next_capacity = CapacityChange.objects.create(
            start_date=datetime.date(4016, 1, 14), resource=self.resource, quantity=3
        )
        self.command = DeleteCapacityChange(self.user, capacity=capacity)
        self.expect_deleted_capacities([capacity.pk, next_capacity.pk], remaining=1)

    def test_deleting_capacity_doesnt_deletes_next_one_if_it_different_to_previous(
        self,
    ):
        CapacityChange.objects.create(
            start_date=datetime.date(4016, 1, 12), resource=self.resource, quantity=4
        )
        capacity = CapacityChange.objects.create(
            start_date=datetime.date(4016, 1, 13), resource=self.resource, quantity=2
        )
        CapacityChange.objects.create(
            start_date=datetime.date(4016, 1, 14), resource=self.resource, quantity=3
        )
        self.command = DeleteCapacityChange(self.user, capacity=capacity)
        self.expect_deleted_capacities([capacity.pk], remaining=2)
