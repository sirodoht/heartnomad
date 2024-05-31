import factory
from faker import Faker
from faker.providers import (
    BaseProvider,
    address,
    date_time,
    lorem,
    misc,
    profile,
    python,
)

factory.Faker.add_provider(misc)
factory.Faker.add_provider(date_time)
factory.Faker.add_provider(python)
factory.Faker.add_provider(lorem)
factory.Faker.add_provider(profile)
factory.Faker.add_provider(address)


class Provider(BaseProvider):
    # Note that the class name _must_ be ``Provider``.
    def slug(self, name):
        fake = Faker()
        value = getattr(fake, name)()
        return value.replace(" ", "-")


factory.Faker.add_provider(Provider)
