import graphene
from graphene import Node
from graphene.types.datetime import DateTime
from graphene_django.types import DjangoObjectType

from api.commands.bookings import RequestBooking
from core.models import Booking


def commandErrorsToGraphQL(errors):
    result = []
    for field_name, messages in errors.iteritems():
        for message in messages:
            result.append([field_name, message])
    return result


class BookingNode(DjangoObjectType):
    class Meta:
        model = Booking
        interfaces = (Node,)


class RequestBookingMutation(graphene.Mutation):
    class Input:
        arrive = DateTime(required=True)
        depart = DateTime(required=True)
        resource = graphene.String(required=True)
        purpose = graphene.String(required=False)
        arrival_time = graphene.String(required=False)
        comments = graphene.String(required=False)

    booking = graphene.Field(BookingNode)
    errors = graphene.List(graphene.List(graphene.String))
    ok = graphene.Boolean()

    @classmethod
    def mutate(cls, root, data, context, info):
        command = RequestBooking(context.user, **data)
        if command.execute():
            return RequestBookingMutation(
                ok=True, booking=command.result().data.get("booking")
            )
        else:
            return RequestBookingMutation(
                ok=False, errors=commandErrorsToGraphQL(command.result().errors)
            )
