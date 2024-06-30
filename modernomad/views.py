from django.http import HttpResponse
from django.shortcuts import render

from core.models import Location, Resource
from gather.models import Event


def index(request):
    recent_events = Event.objects.order_by("-start")[:10]
    locations = Location.objects.filter(visibility="public")
    context = {"locations": locations, "recent_events": recent_events}
    return render(request, "index.html", context)


def about(request):
    return render(request, "about.html")


def drft(request):
    rooms = Resource.objects.all
    return render(request, "drft.html", {"rooms": rooms})


def host(request):
    return render(request, "host.html")


def membership(request):
    return render(request, "membership.html")


def stay(request):
    return render(request, "stay.html")


def ErrorView(request):
    return render(request, "404.html")


def robots(request):
    content = "User-agent: *\n"
    for loc in Location.objects.all():
        content += f"Disallow: /locations/{loc.slug}/team/\n"
        content += f"Disallow: /locations/{loc.slug}/community/\n"
        content += f"Disallow: /locations/{loc.slug}/booking/create/\n"
        content += f"Disallow: /locations/{loc.slug}/events/create/\n"
    return HttpResponse(content, content_type="text/plain")
