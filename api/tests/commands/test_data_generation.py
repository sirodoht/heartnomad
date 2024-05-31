from django.core.management import call_command
from django.test import TransactionTestCase


class DataGenerationTest(TransactionTestCase):
    def test_run_data_generation(self):
        call_command("generate_test_data")
