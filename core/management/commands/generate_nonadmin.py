from random import randint

from django.core.management.base import BaseCommand
from faker import Faker

# from core.factory_apps.communication import EmailtemplateFactory
from core.factory_apps.user import UserFactory


class Command(BaseCommand):
    help = "Generate test data for a development environment."

    def handle(self, *args, **options):
        Faker.seed(1)
        number = str(randint(1_000, 10_000))
        username = f"visitor-{number}"
        first_name = f"Visitor {number}"
        last_name = f"McVisitor {number}"
        UserFactory(username=username, first_name=first_name, last_name=last_name)
        # EmailtemplateFactory()
        self.stdout.write(self.style.SUCCESS("Generated nonadmin test user"))
        self.stdout.write(self.style.SUCCESS(f"username: {username}"))
        self.stdout.write(self.style.SUCCESS("password: password"))
