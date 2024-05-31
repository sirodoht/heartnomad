import graphene

import graphapi.schemas.bookings as bookings
import graphapi.schemas.locations as locations
import graphapi.schemas.occupants as occupants
import graphapi.schemas.resources as resources
import graphapi.schemas.users as users


class Query(
    occupants.Query, locations.Query, users.Query, resources.Query, graphene.ObjectType
):
    pass


class Mutation(graphene.ObjectType):
    request_booking = bookings.RequestBookingMutation.Field()


schema = graphene.Schema(query=Query, mutation=Mutation)
