from django.core.management.base import BaseCommand
from faker import Faker

from core.factory_apps.user import SuperUserFactory


class Command(BaseCommand):
    help = "Generate test admin account for a development environment."

    def handle(self, *args, **options):
        Faker.seed(1)
        SuperUserFactory()
        self.stdout.write(self.style.SUCCESS("Generated `admin`/`password`"))
