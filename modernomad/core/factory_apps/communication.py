from factory.django import DjangoModelFactory

from modernomad.core import models

from . import factory
from .user import UserFactory


# EmailTemplates are the dropdown emails exposed in the location admin
# JKS TODO this does not test the variables exposed in templates
class EmailtemplateFactory(DjangoModelFactory):
    class Meta:
        model = models.EmailTemplate

    body = factory.Faker("paragraph")
    subject = factory.Faker("words")
    name = factory.Faker("words")
    creator = factory.SubFactory(UserFactory)
    shared = factory.Faker("pybool")
    context = models.EmailTemplate.BOOKING
