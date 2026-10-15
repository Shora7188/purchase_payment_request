# -*- coding: utf-8 -*-
{
    "name": "Purchase Payment Request",
    "version": "14.0.1.0.0",
    "category": "Purchases",
    "summary": "Automatic Purchase Payment Requests based on confirmed Purchase Orders",
    "author": "Ashraf Shora",
    "license": "LGPL-3",
    "depends": [
        "purchase",
        "mail",
        "account",
    ],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "data/mail_activity_type.xml",
        "views/purchase_payment_request_views.xml",
        "views/purchase_order_views.xml",
        "wizard/reject_payment_request_views.xml",
        "report/payment_request_report.xml",
        "report/payment_request_report_templates.xml",
    ],
    "installable": True,
    "application": False,
}
