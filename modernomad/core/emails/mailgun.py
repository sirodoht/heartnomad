import logging

import httpx
from django.conf import settings
from django.http import HttpResponse

logger = logging.getLogger(__name__)


def mailgun_send(mailgun_data, files_dict=None):
    logger.debug(f"Mailgun send: {mailgun_data}")
    logger.debug(f"Mailgun files: {files_dict}")

    if not settings.MAILGUN_API_KEY:
        logger.error("Mailgun API key is not defined.")
        return HttpResponse(status=500)

    if not settings.MAILGUN_CAUTION_SEND_REAL_MAIL:
        # We will see this message in the mailgun logs but nothing will
        # actually be delivered. This gets added at the end so it can't be
        # overwritten by other functions.
        mailgun_data["o:testmode"] = "yes"
        logger.debug("mailgun_send: o:testmode={}".format(mailgun_data["o:testmode"]))

    try:
        resp = httpx.post(
            f"https://api.mailgun.net/v2/{settings.LIST_DOMAIN}/messages",
            auth=("api", settings.MAILGUN_API_KEY),
            data=mailgun_data,
            files=files_dict,
        )

        if resp.status_code != 200:
            logger.debug("Mailgun POST returned %d" % resp.status_code)
        return HttpResponse(status=resp.status_code)

    except httpx.ConnectionError:
        logger.error(
            'Connection error. Email "{}" aborted.'.format(mailgun_data["subject"])
        )
        return HttpResponse(status=500)
