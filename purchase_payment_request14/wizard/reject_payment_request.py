# -*- coding: utf-8 -*-

from odoo import fields, models, _
from odoo.exceptions import UserError


class PurchasePaymentRequestRejectWizard(models.TransientModel):
    _name = "purchase.payment.request.reject.wizard"
    _description = "Reject Payment Request"

    request_id = fields.Many2one(
        "purchase.payment.request",
        string="Payment Request",
        required=True,
        readonly=True,
    )
    reason = fields.Text(
        string="Rejection Reason",
        required=True,
    )

    def action_confirm(self):
        self.ensure_one()

        if self.request_id.state in ("approved", "rejected"):
            raise UserError(_(
                "This Payment Request can no longer be rejected."
            ))

        self.request_id.write({
            "state": "rejected",
            "rejection_reason": self.reason,
            "rejected_by": self.env.user.id,
            "rejected_date": fields.Datetime.now(),
        })

        self.request_id.message_post(body=_(
            "Rejected by %s. Reason: %s"
        ) % (
            self.env.user.name,
            self.reason,
        ))

        return {"type": "ir.actions.act_window_close"}
