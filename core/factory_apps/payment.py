from factory.django import DjangoModelFactory
from zoneinfo import ZoneInfo

from core import models

from . import factory
from .location import FeeFactory, LocationFactory, ResourceFactory
from .user import UserFactory


class BillFactory(DjangoModelFactory):
    """Bookings or BillLineItem"""

    class Meta:
        model = models.Bill

    generated_on = factory.Faker("past_datetime", tzinfo=ZoneInfo("UTC"))
    comment = factory.Faker("paragraph")


class BookingBillFactory(DjangoModelFactory):
    class Meta:
        model = models.BookingBill

    generated_on = factory.Faker("past_datetime")
    comment = factory.Faker("paragraph")


class BillLineItem(DjangoModelFactory):
    class Meta:
        model = models.BillLineItem

    bill = factory.SubFactory(BillFactory)
    fee = factory.SubFactory(FeeFactory)

    description = factory.Faker("words")
    amount = factory.Faker("pydecimal", left_digits=3, positive=True)
    paid_by_house = factory.Faker("pybool")
    custom = factory.Faker("pybool")


class UseFactory(DjangoModelFactory):
    class Meta:
        model = models.Use

    created = factory.Faker("past_datetime", tzinfo=ZoneInfo("UTC"))
    updated = factory.Faker("past_datetime", tzinfo=ZoneInfo("UTC"))

    location = factory.SubFactory(LocationFactory)
    user = factory.SubFactory(UserFactory)
    resource = factory.SubFactory(ResourceFactory)

    status = models.Use.PENDING
    arrive = factory.Faker("future_date", tzinfo=ZoneInfo("UTC"))
    depart = factory.Faker("future_date", tzinfo=ZoneInfo("UTC"))
    arrival_time = factory.Faker("words")
    purpose = factory.Faker("paragraph")
    last_msg = factory.Faker("past_datetime", tzinfo=ZoneInfo("UTC"))
    accounted_by = models.Use.FIAT


class BookingFactory(DjangoModelFactory):
    # deprecated fields not modeled in factory
    class Meta:
        model = models.Booking

    created = factory.Faker("past_datetime", tzinfo=ZoneInfo("UTC"))
    updated = factory.Faker("past_datetime", tzinfo=ZoneInfo("UTC"))

    comments = factory.Faker("paragraph")
    rate = factory.Faker("pydecimal", left_digits=3, positive=True)
    uuid = factory.Faker("uuid4")

    bill = factory.SubFactory(BookingBillFactory)
    use = factory.SubFactory(UseFactory)

    @factory.post_generation
    def suppressed_fees(self, create, extracted, **kwargs):
        if not create:
            # Simple build, do nothing.
            return

        if extracted:
            # A list of groups were passed in, use them
            for fee in extracted:
                self.suppressed_fees.add(fee)


class PaymentFactory(DjangoModelFactory):
    class Meta:
        model = models.Payment

    bill = factory.SubFactory(BillFactory)
    user = factory.SubFactory(UserFactory)
    payment_date = factory.Faker("past_datetime", tzinfo=ZoneInfo("UTC"))

    # payment_service and payment_method may be empty so ignoring those
    paid_amount = factory.Faker("pydecimal", left_digits=3, positive=True)
    transaction_id = factory.Faker("uuid4")


class UseNoteFactory(DjangoModelFactory):
    class Meta:
        model = models.UseNote
