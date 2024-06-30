from graphene import Boolean, List, Node, ObjectType
from graphene_django.filter.fields import DjangoFilterConnectionField
from graphene_django.types import DjangoObjectType

from core.models import Fee, Location

from .resources import ResourceNode


class FeeNode(DjangoObjectType):
    class Meta:
        model = Fee
        interfaces = (Node,)


class LocationNode(DjangoObjectType):
    fees = List(lambda: FeeNode, paid_by_house=Boolean())
    resources = List(
        lambda: ResourceNode,
        has_future_capacity=Boolean(),
        has_future_drft_capacity=Boolean(),
    )

    class Meta:
        model = Location
        interfaces = (Node,)
        filter_fields = ["slug"]

    def resolve_fees(self, info, **kwargs):
        query = Fee.objects.filter(locationfee__location=self)
        query = query.filter(**kwargs)

        return query

    def resolve_resources(self, info, **kwargs):
        if kwargs.get("has_future_capacity", False):
            resources = self.rooms_with_future_capacity()
        elif kwargs.get("has_future_drft_capacity", False):
            resources = self.rooms_with_future_drft_capacity()
        else:
            resources = self.resources.all()
        return resources


class Query(ObjectType):
    all_locations = DjangoFilterConnectionField(LocationNode)
