import logging

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    # help = "Set all users to given email, password and customer ID"
    # args = "[email_address] [password] [customer_id]"
    requires_system_checks = True

    def handle(self, *labels, **options):
        # if not labels or len(labels) < 1: raise CommandError('Args: <email_address> <password> <customer_id>')

        logger.debug("Checking {User.objects.all().count()} users...")

        nonalpha = []
        dup_emails = []
        cap_emails = []
        for u in User.objects.filter(is_active=True):
            if not u.username.replace("_", "").isalnum():
                nonalpha.append(u)
                logger.debug(f"{u.username}: not alphanumeric")
                logger.debug(f"    UserID: {u.id}")
                logger.debug(f"    Last Login: {u.last_login}")

            if u.email not in dup_emails:
                others_with_email = User.objects.filter(email=u.email, is_active=True)
                if others_with_email.count() > 1:
                    dup_emails.append(u.email)
                    logger.debug(f"{u.email}: Duplicate email")
                    for o in others_with_email:
                        logger.debug(f"    {o.username}/{o.id}: {o.last_login}")

            if u.email != u.email.lower():
                cap_emails.append(u)
                logger.debug(f"{u.username}: capitolized email")
                logger.debug(f"    UserID: {u.id}")
                logger.debug(f"    Last Login: {u.last_login}")

        logger.debug(f"{len(nonalpha)} alphanumeric problems")
        logger.debug(f"{len(dup_emails)} duplicate email problems")
        logger.debug(f"{len(cap_emails)} capitolized emails")
