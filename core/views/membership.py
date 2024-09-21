from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from core import models, payment_gateway


@login_required
def manage(request):
    return render(
        request,
        "membership.html",
        {
            "stripe_publishable_key": settings.STRIPE_PUBLISHABLE_KEY,
            "has_membership": models.Membership.objects.filter(
                user=request.user
            ).exists(),
        },
    )


@login_required
def charge(request):
    if models.Membership.objects.filter(user=request.user).exists():
        messages.info(request, "Looks like you are already a member.")
        return redirect("user_detail", username=request.user.username)

    payment_gateway.charge_short_term_membership(request.user)

    models.Membership.objects.create(user=request.user)

    messages.info(request, "Thanks! Payment received.")
    return redirect("user_detail", username=request.user.username)


@login_required
def enable(request):
    if models.Membership.objects.filter(user=request.user).exists():
        messages.info(request, "Looks like you are already a member.")
        return redirect("user_detail", username=request.user.username)

    models.Membership.objects.create(user=request.user)
    messages.info(request, "Membership created")
    return redirect("user_detail", username=request.user.username)
