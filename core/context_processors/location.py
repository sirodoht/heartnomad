import re

from core.models import Location


def network_locations(request):
    return {"network_locations": Location.objects.all()}


def location_variables(request):
    match = re.match(r"^/locations/(?P<location_slug>[^/]*)/.*", request.path)
    if match:
        location_slug = match.group("location_slug")
        location = Location.objects.filter(slug=location_slug).first()
        if location:
            location_about_path = f"locations/{location_slug}/about/"
            location_stay_path = f"locations/{location_slug}/stay/"
            return {
                "location": location,
                "location_about_path": location_about_path,
                "location_stay_path": location_stay_path,
            }
    return {}
