"""
Central notification dispatch.

Usage:
    from notifications.service import notify, bulk_notify, render_notification
    from notifications.models import Notification

    ctx = {'job_no': '2024-001', 'actor': 'Ahmet Yılmaz', ...}
    title, body, link = render_notification(Notification.JOB_ON_HOLD, ctx)
    bulk_notify(users, Notification.JOB_ON_HOLD, title=title, body=body, link=link)
"""
from __future__ import annotations

import logging
import threading
from typing import Iterable

from django.conf import settings

from .models import Notification, NotificationConfig, NotificationPreference

logger = logging.getLogger(__name__)

_BASE_URL = 'https://ofis.gemcore.com.tr'

# ---------------------------------------------------------------------------
# Default preferences (send_email, send_in_app)
# Rows only exist in NotificationPreference when the user deviates from these.
# ---------------------------------------------------------------------------
NOTIFICATION_DEFAULTS: dict[str, tuple[bool, bool]] = {
    Notification.PR_APPROVAL_REQUESTED:    (True,  True),
    Notification.PR_APPROVED:              (True,  True),
    Notification.PR_REJECTED:              (True,  True),
    Notification.PR_PO_CREATED:            (True,  True),
    Notification.OT_APPROVAL_REQUESTED:    (True,  True),
    Notification.OT_APPROVED:              (True,  True),
    Notification.OT_REJECTED:              (True,  True),
    Notification.QC_REVIEW_SUBMITTED:      (True,  True),
    Notification.QC_REVIEW_APPROVED:       (True,  True),
    Notification.QC_REVIEW_REJECTED:       (True,  True),
    Notification.NCR_CREATED:              (True,  True),
    Notification.NCR_SUBMITTED:            (True,  True),
    Notification.NCR_APPROVED:             (True,  True),
    Notification.NCR_REJECTED:             (True,  True),
    Notification.NCR_ASSIGNED:             (True,  True),
    Notification.SALES_APPROVAL_REQUESTED: (True,  True),
    Notification.SALES_APPROVED:           (True,  True),
    Notification.SALES_REJECTED:           (True,  True),
    Notification.SALES_CONSULTATION:       (True,  True),
    Notification.SALES_CONVERTED:          (True,  True),
    Notification.SUB_APPROVAL_REQUESTED:   (True,  True),
    Notification.SUB_APPROVED:             (True,  True),
    Notification.SUB_REJECTED:             (True,  True),
    Notification.PLAN_APPROVAL_REQUESTED:  (True,  True),
    Notification.PLAN_APPROVED:            (True,  True),
    Notification.PLAN_REJECTED:            (True,  True),
    Notification.PLAN_DR_APPROVED:         (True,  True),
    Notification.DRAWING_RELEASED:         (True,  True),
    Notification.REVISION_REQUESTED:       (True,  True),
    Notification.REVISION_APPROVED:        (True,  True),
    Notification.REVISION_COMPLETED:       (True,  True),
    Notification.REVISION_REJECTED:        (True,  True),
    Notification.JOB_ON_HOLD:              (True,  True),
    Notification.JOB_RESUMED:              (False, True),
    Notification.TOPIC_MENTION:            (True,  True),
    Notification.COMMENT_MENTION:          (True,  True),
    Notification.NEW_COMMENT:              (False, True),
    Notification.PASSWORD_RESET:           (True,  False),
}


# ---------------------------------------------------------------------------
# Notification config defaults — source of truth for seed migration + fallback
# ---------------------------------------------------------------------------
NOTIFICATION_CONFIG_DEFAULTS: dict[str, dict] = {
    Notification.TOPIC_MENTION: {
        'title': '[Etiketlendiniz] {job_no} \u2013 {topic_title}',
        'body': (
            '{actor} sizi bir tartışma konusunda etiketledi.\n'
            'İş Emri: {job_no} - {job_title}\n'
            'Konu: {topic_title}\n\n'
            '{topic_content}\n\n'
            '{link}'
        ),
        'link': f'{_BASE_URL}/projects/project-tracking/?job_no={{job_no}}&topic_id={{topic_id}}',
        'vars': ['actor', 'job_no', 'job_title', 'topic_title', 'topic_content', 'topic_id', 'link'],
    },
    Notification.NEW_COMMENT: {
        'title': '[Yeni Yorum] {job_no} \u2013 {topic_title}',
        'body': (
            '{actor} tartışma konunuza yorum yaptı.\n\n'
            '{comment_content}\n\n'
            '{link}'
        ),
        'link': f'{_BASE_URL}/projects/project-tracking/?job_no={{job_no}}&topic_id={{topic_id}}',
        'vars': ['actor', 'job_no', 'topic_title', 'comment_content', 'topic_id', 'link'],
    },
    Notification.COMMENT_MENTION: {
        'title': '[Yorumda Etiketlendiniz] {job_no} \u2013 {topic_title}',
        'body': (
            '{actor} sizi bir yorumda etiketledi.\n\n'
            '{comment_content}\n\n'
            '{link}'
        ),
        'link': f'{_BASE_URL}/projects/project-tracking/?job_no={{job_no}}&topic_id={{topic_id}}',
        'vars': ['actor', 'job_no', 'topic_title', 'comment_content', 'topic_id', 'link'],
    },
    Notification.DRAWING_RELEASED: {
        'title': '[Teknik Çizim Yayınlandı] {job_no} Rev.{revision}',
        'body': (
            '{actor} yeni teknik çizim yayınladı.\n'
            'İş Emri: {job_no} - {job_title}\n'
            'Revizyon: {revision}\n'
            'Hardcopy: {hardcopy_count} set\n\n'
            'Klasör Yolu:\n{folder_path}\n\n'
            'Değişiklikler:\n{changelog}\n\n'
            '{link}'
        ),
        'link': f'{_BASE_URL}/projects/project-tracking/?job_no={{job_no}}&topic_id={{topic_id}}',
        'vars': ['actor', 'job_no', 'job_title', 'revision', 'hardcopy_count', 'folder_path', 'changelog', 'topic_id', 'link'],
    },
    Notification.REVISION_REQUESTED: {
        'title': '[Revizyon Talebi] {job_no} Rev.{revision}',
        'body': (
            '{actor} teknik çizimler için revizyon talep etti.\n'
            'İş Emri: {job_no} - {job_title}\n'
            'Mevcut Revizyon: {revision}\n\n'
            'Talep Nedeni:\n{topic_content}\n\n'
            'Bu talep onay beklemektedir.\n\n'
            '{link}'
        ),
        'link': f'{_BASE_URL}/projects/project-tracking/?job_no={{job_no}}&topic_id={{topic_id}}',
        'vars': ['actor', 'job_no', 'job_title', 'revision', 'topic_content', 'topic_id', 'link'],
    },
    Notification.REVISION_APPROVED: {
        'title': '[Revizyon Onaylandı] {job_no}',
        'body': (
            '{actor} revizyon talebini onayladı.\n'
            'İş Emri: {job_no} - {job_title}\n'
            'Konu: {topic_title}\n\n'
            'İş emri revizyon süresince beklemeye alınmıştır.\n\n'
            '{link}'
        ),
        'link': f'{_BASE_URL}/projects/project-tracking/?job_no={{job_no}}&topic_id={{topic_id}}',
        'vars': ['actor', 'job_no', 'job_title', 'topic_title', 'topic_id', 'link'],
    },
    Notification.REVISION_COMPLETED: {
        'title': '[Revizyon Tamamlandı] {job_no} Rev.{revision}',
        'body': (
            '{actor} revizyonu tamamladı ve yeni çizim yayınladı.\n'
            'İş Emri: {job_no} - {job_title}\n'
            'Yeni Revizyon: {revision}\n\n'
            'Değişiklikler:\n{changelog}\n\n'
            'Klasör Yolu:\n{folder_path}\n\n'
            'İş emri devam etmektedir.\n\n'
            '{link}'
        ),
        'link': f'{_BASE_URL}/projects/project-tracking/?job_no={{job_no}}&topic_id={{topic_id}}',
        'vars': ['actor', 'job_no', 'job_title', 'revision', 'changelog', 'folder_path', 'topic_id', 'link'],
    },
    Notification.REVISION_REJECTED: {
        'title': '[Revizyon Talebi Reddedildi] {job_no} Rev.{revision}',
        'body': (
            '{actor} revizyon talebini reddetti.\n'
            'İş Emri: {job_no} - {job_title}\n'
            'Konu: {topic_title}\n\n'
            'Red Nedeni:\n{reason}\n\n'
            '{link}'
        ),
        'link': f'{_BASE_URL}/projects/project-tracking/?job_no={{job_no}}&topic_id={{topic_id}}',
        'vars': ['actor', 'job_no', 'job_title', 'topic_title', 'reason', 'topic_id', 'link'],
    },
    Notification.JOB_ON_HOLD: {
        'title': '[İş Emri Beklemede] {job_no}',
        'body': (
            '{job_no} numaralı iş emri beklemeye alınmıştır.\n'
            'Tamamlanana kadar bu iş emri üzerindeki çalışmalara devam etmeyiniz.\n\n'
            'Neden: {reason}\n\n'
            '{link}'
        ),
        'link': f'{_BASE_URL}/projects/project-tracking/?job_no={{job_no}}',
        'vars': ['job_no', 'reason', 'link'],
    },
    Notification.JOB_RESUMED: {
        'title': '[İş Emri Devam Ediyor] {job_no}',
        'body': (
            '{job_no} numaralı iş emri devam etmektedir.\n'
            'Çalışmalara devam edebilirsiniz.\n\n'
            '{revision}'
            '{link}'
        ),
        'link': f'{_BASE_URL}/projects/project-tracking/?job_no={{job_no}}',
        'vars': ['job_no', 'revision', 'link'],
    },
    Notification.SALES_APPROVAL_REQUESTED: {
        'title': '[Onay Gerekli] Satış Teklifi: {offer_no}',
        'body': (
            '{offer_no} numaralı "{offer_title}" teklifi onayınızı bekliyor.\n'
            'Müşteri: {customer}\n'
            'Tutar: {total_price} EUR'
        ),
        'link': '',
        'vars': ['offer_no', 'offer_title', 'customer', 'total_price', 'link'],
    },
    Notification.SALES_APPROVED: {
        'title': '[Satış Teklifi Onaylandı] {offer_no}',
        'body': '{offer_no} numaralı "{offer_title}" teklifi onaylandı.',
        'link': '',
        'vars': ['offer_no', 'offer_title', 'customer', 'link'],
    },
    Notification.SALES_REJECTED: {
        'title': '[Satış Teklifi Reddedildi] {offer_no}',
        'body': '{offer_no} numaralı "{offer_title}" teklifi reddedildi.',
        'link': '',
        'vars': ['offer_no', 'offer_title', 'customer', 'link'],
    },
    Notification.SALES_CONVERTED: {
        'title': '[Yeni İş Emri] {job_no}',
        'body': (
            '{offer_no} numaralı "{offer_title}" teklifi iş emrine dönüştürüldü.\n'
            'Müşteri: {customer}\n'
            'İş Emri No: {job_no}\n'
            'İş Emri Başlığı: {job_title}'
        ),
        'link': '',
        'vars': ['offer_no', 'offer_title', 'customer', 'job_no', 'job_title', 'link'],
    },
    Notification.SALES_CONSULTATION: {
        'title': '[Danışma Talebi] {offer_no} – {task_title}',
        'body': (
            '{offer_no} numaralı "{offer_title}" teklifi için danışma görevi oluşturuldu.\n'
            'Müşteri: {customer}\n'
            'Departman: {department}\n'
            'Görev: {task_title}\n'
            '{notes}'
        ),
        'link': '',
        'vars': ['offer_no', 'offer_title', 'customer', 'department', 'department_code', 'task_id', 'task_title', 'notes', 'link'],
    },
    Notification.PR_APPROVAL_REQUESTED: {
        'title': '[Onay Gerekli] Satınalma Talebi #{pr_id} \u2013 {pr_title}',
        'body': (
            'Satınalma talebi (#{pr_id} \u2013 {pr_title}) için onayınız bekleniyor.\n'
            'Aşama: {stage_name} (Gerekli onay sayısı: {required_approvals})\n'
            'Öncelik: {priority}\n'
            'Talep Eden: {requestor}\n\n'
            'Not: Bu bildirim nedeni: {reason}.\n\n'
            '{link}'
        ),
        'link': f'{_BASE_URL}/procurement/purchase-requests/pending/?talep={{pr_id}}',
        'vars': ['pr_id', 'pr_title', 'stage_name', 'required_approvals', 'priority', 'requestor', 'reason', 'link'],
    },
    Notification.PR_APPROVED: {
        'title': '[Satınalma Talebi Onaylandı] PR #{pr_id} \u2013 {pr_title}',
        'body': (
            'Satınalma talebiniz (#{pr_id} \u2013 {pr_title}) onaylandı.\n'
            '{comment}\n\n'
            '{link}'
        ),
        'link': f'{_BASE_URL}/procurement/purchase-requests/pending/?talep={{pr_id}}',
        'vars': ['pr_id', 'pr_title', 'comment', 'link'],
    },
    Notification.PR_REJECTED: {
        'title': '[Satınalma Talebi Reddedildi] PR #{pr_id} \u2013 {pr_title}',
        'body': (
            'Satınalma talebiniz (#{pr_id} \u2013 {pr_title}) reddedildi.\n'
            '{comment}\n\n'
            '{link}'
        ),
        'link': f'{_BASE_URL}/procurement/purchase-requests/pending/?talep={{pr_id}}',
        'vars': ['pr_id', 'pr_title', 'comment', 'link'],
    },
    Notification.PR_PO_CREATED: {
        'title': '[PO Oluşturuldu] PR #{pr_id} \u2013 {pr_title}',
        'body': (
            'Satınalma talebi (PR #{pr_id} \u2013 {pr_title}) onaylandı ve '
            'aşağıdaki satınalma siparişleri oluşturuldu:\n\n{po_list}\n\n'
            '{link}'
        ),
        'link': f'{_BASE_URL}/procurement/purchase-requests/pending/?talep={{pr_id}}',
        'vars': ['pr_id', 'pr_title', 'po_list', 'link'],
    },
    Notification.OT_APPROVAL_REQUESTED: {
        'title': '[Onay Gerekli] Mesai Talebi #{ot_id} \u2013 {ot_title}',
        'body': (
            'Mesai talebi (#{ot_id}) için onayınız bekleniyor.\n'
            'Aşama: {stage_name} (Gerekli onay sayısı: {required_approvals})\n'
            'Talep Eden: {requestor}\n'
            'Takım: {team}\n'
            'Neden: {reason}\n\n'
            'Not: Bildirim nedeni: {reason}.\n\n'
            '{link}'
        ),
        'link': f'{_BASE_URL}/general/overtime/pending/?request={{ot_id}}',
        'vars': ['ot_id', 'ot_title', 'stage_name', 'required_approvals', 'requestor', 'team', 'reason', 'link'],
    },
    Notification.OT_APPROVED: {
        'title': '[Mesai Talebi Onaylandı] OT #{ot_id} \u2013 {ot_title}',
        'body': (
            'Mesai talebiniz (#{ot_id}) onaylandı.\n'
            '{comment}\n\n'
            '{entries_summary}\n\n'
            '{link}'
        ),
        'link': f'{_BASE_URL}/general/overtime/pending/?request={{ot_id}}',
        'vars': ['ot_id', 'ot_title', 'comment', 'requestor', 'team', 'entries_summary', 'link'],
    },
    Notification.OT_REJECTED: {
        'title': '[Mesai Talebi Reddedildi] OT #{ot_id} \u2013 {ot_title}',
        'body': (
            'Mesai talebiniz (#{ot_id}) reddedildi.\n'
            '{comment}\n\n'
            '{link}'
        ),
        'link': f'{_BASE_URL}/general/overtime/pending/?request={{ot_id}}',
        'vars': ['ot_id', 'ot_title', 'comment', 'link'],
    },
    Notification.QC_REVIEW_SUBMITTED: {
        'title': '[KK İncelemesi] {job_no} \u2014 {task_title}',
        'body': (
            'Görev KK incelemesi için gönderildi.\n\n'
            'İş Emri: {job_no}\n'
            'Görev: {task_title}\n'
            'Departman: {department}\n'
            'Gönderen: {actor}\n'
            'İnceleme ID: #{review_id}\n'
            'Toplam: {count} inceleme'
        ),
        'link': '',
        'vars': ['job_no', 'task_title', 'department', 'actor', 'review_id', 'count', 'review_ids', 'link'],
    },
    Notification.QC_REVIEW_APPROVED: {
        'title': '[KK Onaylandı] {job_no} \u2014 {task_title}',
        'body': (
            'İş Emri {job_no} / Görev: {task_title} KK incelemesi onaylandı.\n'
            'İnceleme ID: #{review_id}'
        ),
        'link': '',
        'vars': ['job_no', 'task_title', 'review_id', 'link'],
    },
    Notification.QC_REVIEW_REJECTED: {
        'title': '[KK Reddedildi] {job_no} \u2014 {task_title}',
        'body': (
            'Gönderdiğiniz KK incelemesi reddedildi.\n\n'
            'İş Emri: {job_no}\n'
            'Görev: {task_title}\n'
            'İnceleme ID: #{review_id}\n'
            'Yorum: {comment}\n\n'
            'Otomatik NCR oluşturuldu.'
        ),
        'link': '',
        'vars': ['job_no', 'task_title', 'review_id', 'comment', 'link'],
    },
    Notification.NCR_CREATED: {
        'title': '[NCR Oluşturuldu] {ncr_number} \u2014 {job_no}',
        'body': (
            'KK incelemesi reddedildi ve NCR otomatik oluşturuldu.\n\n'
            'NCR No: {ncr_number}\n'
            'İş Emri: {job_no}\n'
            'Görev: {task_title}\n'
            'Açıklama: {description}'
        ),
        'link': '',
        'vars': ['ncr_number', 'job_no', 'task_title', 'description', 'link'],
    },
    Notification.NCR_SUBMITTED: {
        'title': '[NCR Onay Bekliyor] {ncr_number} \u2014 {ncr_title}',
        'body': (
            'NCR onayınızı bekliyor.\n\n'
            'NCR No: {ncr_number}\n'
            'Başlık: {ncr_title}\n'
            'İş Emri: {job_no}\n'
            'Önem: {severity}\n'
            'Açıklama: {description}'
        ),
        'link': '',
        'vars': ['ncr_number', 'ncr_title', 'job_no', 'severity', 'description', 'link'],
    },
    Notification.NCR_APPROVED: {
        'title': '[NCR Onaylandı] {ncr_number} \u2014 {ncr_title}',
        'body': (
            'NCR onaylandı.\n\n'
            'NCR No: {ncr_number}\n'
            'Başlık: {ncr_title}\n'
            'İş Emri: {job_no}\n'
            'Önem: {severity}'
        ),
        'link': '',
        'vars': ['ncr_number', 'ncr_title', 'job_no', 'severity', 'link'],
    },
    Notification.NCR_REJECTED: {
        'title': '[NCR Reddedildi] {ncr_number} \u2014 {ncr_title}',
        'body': (
            'NCR reddedildi.\n\n'
            'NCR No: {ncr_number}\n'
            'Başlık: {ncr_title}\n'
            'İş Emri: {job_no}\n'
            'Yorum: {comment}\n\n'
            'Lütfen NCR\'ı güncelleyip yeniden gönderin.'
        ),
        'link': '',
        'vars': ['ncr_number', 'ncr_title', 'job_no', 'comment', 'link'],
    },
    Notification.NCR_ASSIGNED: {
        'title': '[NCR Atandı] {ncr_number} \u2014 {ncr_title}',
        'body': (
            'Size bir NCR atandı.\n\n'
            'NCR No: {ncr_number}\n'
            'Başlık: {ncr_title}\n'
            'İş Emri: {job_no}\n'
            'Önem: {severity}\n'
            'Açıklama: {description}'
        ),
        'link': '',
        'vars': ['ncr_number', 'ncr_title', 'job_no', 'severity', 'description', 'link'],
    },
    Notification.SUB_APPROVAL_REQUESTED: {
        'title': '[Onay Gerekli] Taşeron Hakedişi \u2013 {subcontractor} {year}/{month}',
        'body': (
            '{subcontractor} taşeronuna ait {year}/{month} dönemi hakedişi onayınızı bekliyor.\n'
            'Toplam Tutar: {currency} {total}\n'
            '{reason}'
        ),
        'link': '',
        'vars': ['subcontractor', 'year', 'month', 'currency', 'total', 'reason', 'link'],
    },
    Notification.SUB_APPROVED: {
        'title': '[Taşeron Hakedişi Onaylandı] {subcontractor} {year}/{month}',
        'body': (
            'Taşeron hakedişi ({subcontractor} \u2013 {year}/{month}) onaylandı.\n'
            'Toplam Tutar: {currency} {total}\n'
            '{comment}'
        ),
        'link': '',
        'vars': ['subcontractor', 'year', 'month', 'currency', 'total', 'comment', 'link'],
    },
    Notification.SUB_REJECTED: {
        'title': '[Taşeron Hakedişi Reddedildi] {subcontractor} {year}/{month}',
        'body': (
            'Taşeron hakedişi ({subcontractor} \u2013 {year}/{month}) reddedildi.\n'
            'Toplam Tutar: {currency} {total}\n'
            '{comment}'
        ),
        'link': '',
        'vars': ['subcontractor', 'year', 'month', 'currency', 'total', 'comment', 'link'],
    },
    Notification.PLAN_APPROVAL_REQUESTED: {
        'title': '[Onay Gerekli] Departman Talebi #{dr_id} \u2013 {dr_title}',
        'body': (
            'Departman talebi (#{dr_id} \u2013 {dr_title}) için onayınız bekleniyor.\n'
            'Aşama: {stage_name} (Gerekli onay sayısı: {required_approvals})\n'
            'Öncelik: {priority}\n'
            'Talep Eden: {requestor}\n\n'
            'Not: Bildirim nedeni: {reason}.\n\n'
            '{link}'
        ),
        'link': f'{_BASE_URL}/general/department-requests/?request={{dr_id}}',
        'vars': ['dr_id', 'dr_title', 'stage_name', 'required_approvals', 'priority', 'requestor', 'reason', 'link'],
    },
    Notification.PLAN_APPROVED: {
        'title': '[Departman Talebi Onaylandı] DR #{dr_id} \u2013 {dr_title}',
        'body': (
            'Departman talebi (#{dr_id} \u2013 {dr_title}) onaylandı.\n'
            '{comment}\n\n'
            'Departman: {department}\n'
            'Talep Eden: {requestor}\n'
            'Öncelik: {priority}\n\n'
            '{link}'
        ),
        'link': f'{_BASE_URL}/general/department-requests/?request={{dr_id}}',
        'vars': ['dr_id', 'dr_title', 'comment', 'department', 'requestor', 'priority', 'link'],
    },
    Notification.PLAN_REJECTED: {
        'title': '[Departman Talebi Reddedildi] DR #{dr_id} \u2013 {dr_title}',
        'body': (
            'Departman talebiniz (#{dr_id} \u2013 {dr_title}) reddedildi.\n'
            '{comment}\n\n'
            '{link}'
        ),
        'link': f'{_BASE_URL}/general/department-requests/?request={{dr_id}}',
        'vars': ['dr_id', 'dr_title', 'comment', 'link'],
    },
    Notification.PLAN_DR_APPROVED: {
        'title': '[Departman Talebi Planlama Onayladı] DR #{dr_id} \u2013 {dr_title}',
        'body': (
            'Departman talebi (#{dr_id} \u2013 {dr_title}) planlama tarafından onaylandı.\n\n'
            '{link}'
        ),
        'link': f'{_BASE_URL}/general/department-requests/?request={{dr_id}}',
        'vars': ['dr_id', 'dr_title', 'link'],
    },
    Notification.PASSWORD_RESET: {
        'title': '[Parola Sıfırlama Talebi] {username}',
        'body': (
            'Parola sıfırlama talebi gönderildi.\n\n'
            'Kullanıcı: {full_name} (username: {username})\n'
            'Takım: {team}\n'
            'Tarih: {requested_at}\n\n'
            'Lütfen sistemden onaylayın.'
        ),
        'link': '',
        'vars': ['username', 'full_name', 'team', 'requested_at', 'link'],
    },
}


# ---------------------------------------------------------------------------
# Template cache — module-level, populated once per Gunicorn worker
# ---------------------------------------------------------------------------
_config_cache: dict[str, dict] = {}
_cache_lock = threading.Lock()
_cache_populated = False


def _warm_config_cache() -> None:
    global _cache_populated
    with _cache_lock:
        if _cache_populated:
            return
        try:
            for cfg in NotificationConfig.objects.all():
                _config_cache[cfg.notification_type] = {
                    'title':      cfg.title_template,
                    'body':       cfg.body_template,
                    'link':       cfg.link_template,
                    'send_email': cfg.default_send_email,
                    'send_inapp': cfg.default_send_in_app,
                }
            _cache_populated = True
        except Exception:
            logger.exception('Failed to warm notification config cache')


def invalidate_config_cache() -> None:
    """Call after admin writes to NotificationConfig to force cache refresh."""
    global _cache_populated
    with _cache_lock:
        _config_cache.clear()
        _cache_populated = False


def _get_config_tmpl(notification_type: str) -> dict:
    if not _cache_populated:
        _warm_config_cache()
    if notification_type in _config_cache:
        return _config_cache[notification_type]
    default = NOTIFICATION_CONFIG_DEFAULTS.get(notification_type, {})
    return {
        'title': default.get('title', ''),
        'body':  default.get('body', ''),
        'link':  default.get('link', ''),
    }


class _SafeDict(dict):
    """Returns empty string for missing keys instead of raising KeyError."""
    def __missing__(self, key):
        return ''


def render_notification(
    notification_type: str,
    context: dict,
    route_link: str = '',
) -> tuple[str, str, str]:
    """
    Render title, body, link for a notification type using DB template + context.

    Link priority:
      1. route_link (NotificationConfig.link_template rendered at call site for routable types)
      2. link_template rendered with context
      3. empty string

    Returns (title, body, link).
    """
    tmpl  = _get_config_tmpl(notification_type)
    safe  = _SafeDict(context)
    title = tmpl['title'].format_map(safe)
    link  = (route_link or tmpl['link']).format_map(safe)
    # Re-render body with 'link' available so {link} placeholders in body templates resolve
    safe['link'] = link
    body  = tmpl['body'].format_map(safe)
    return title, body, link


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def get_route(notification_type: str) -> tuple:
    """
    Return (users_queryset, rendered_link) for a routable notification type.
    Merges explicit users M2M with all active members of configured teams.
    Returns (empty queryset, '') if no config exists or the route is disabled.
    """
    from django.contrib.auth.models import User
    try:
        cfg = NotificationConfig.objects.get(notification_type=notification_type)
        if not cfg.enabled:
            return User.objects.none(), ''

        explicit_ids = set(cfg.users.filter(is_active=True).values_list('id', flat=True))

        team_ids = set()
        if cfg.teams:
            from users.models import UserProfile
            team_ids = set(
                UserProfile.objects.filter(team__in=cfg.teams)
                .values_list('user_id', flat=True)
            )

        all_ids = explicit_ids | team_ids
        link = cfg.link_template or ''
        if not all_ids:
            return User.objects.none(), link
        return User.objects.filter(id__in=all_ids, is_active=True), link
    except NotificationConfig.DoesNotExist:
        return User.objects.none(), ''


def get_route_users(notification_type: str):
    """Return just the users queryset for a routable notification type."""
    users, _ = get_route(notification_type)
    return users


# ---------------------------------------------------------------------------
# Core dispatch
# ---------------------------------------------------------------------------

def _get_system_defaults(notification_type: str) -> tuple[bool, bool]:
    """Return system-level (send_email, send_in_app) from config cache, then hardcoded dict."""
    if not _cache_populated:
        _warm_config_cache()
    cached = _config_cache.get(notification_type)
    if cached and 'send_email' in cached:
        return cached['send_email'], cached['send_inapp']
    return NOTIFICATION_DEFAULTS.get(notification_type, (True, True))


def _get_user_prefs(user, notification_type: str) -> tuple[bool, bool]:
    """Return (send_email, send_in_app) for a user, falling back to system defaults."""
    try:
        pref = NotificationPreference.objects.get(user=user, notification_type=notification_type)
        return pref.send_email, pref.send_in_app
    except NotificationPreference.DoesNotExist:
        return _get_system_defaults(notification_type)


def notify(
    user,
    notification_type: str,
    title: str,
    body: str = '',
    link: str = '',
    source_type: str = '',
    source_id: str | int | None = None,
    email_subject: str | None = None,
    email_body: str | None = None,
) -> Notification | None:
    """
    Dispatch a single notification to one user.

    Creates an in-app Notification record if the user's preference allows.
    Enqueues a Cloud Tasks email job if the user's preference allows.
    Returns the created Notification (or None if in-app is disabled).
    """
    send_email, send_in_app = _get_user_prefs(user, notification_type)

    notification = None
    if send_in_app:
        try:
            notification = Notification.objects.create(
                user=user,
                notification_type=notification_type,
                category=Notification.CATEGORY_MAP.get(notification_type, ''),
                title=title,
                body=body,
                link=link,
                source_type=source_type,
                source_id=str(source_id) if source_id is not None else '',
            )
        except Exception:
            logger.exception('Failed to create in-app notification for user %s type %s', user, notification_type)

    if send_email and getattr(user, 'email', ''):
        _enqueue_email(
            to=user.email,
            subject=email_subject or title,
            body=email_body or body,
            notification_id=notification.id if notification else None,
        )

    return notification


def bulk_notify(
    users: Iterable,
    notification_type: str,
    title: str,
    body: str = '',
    link: str = '',
    source_type: str = '',
    source_id: str | int | None = None,
    email_subject: str | None = None,
    email_body: str | None = None,
) -> list[Notification]:
    """
    Dispatch the same notification to multiple users efficiently.
    Uses bulk_create for in-app records (single INSERT), then enqueues
    one email task per eligible recipient.
    """
    users = list(users)
    if not users:
        return []

    user_ids = [u.id for u in users]
    pref_map: dict[int, tuple[bool, bool]] = {}
    for pref in NotificationPreference.objects.filter(
        user_id__in=user_ids,
        notification_type=notification_type,
    ):
        pref_map[pref.user_id] = (pref.send_email, pref.send_in_app)

    default_email, default_inapp = _get_system_defaults(notification_type)

    to_create = []
    email_recipients: list[tuple[str, int | None]] = []

    for user in users:
        send_email, send_in_app = pref_map.get(user.id, (default_email, default_inapp))
        if send_in_app:
            to_create.append(Notification(
                user=user,
                notification_type=notification_type,
                category=Notification.CATEGORY_MAP.get(notification_type, ''),
                title=title,
                body=body,
                link=link,
                source_type=source_type,
                source_id=str(source_id) if source_id is not None else '',
            ))
        if send_email and getattr(user, 'email', ''):
            email_recipients.append((user.email, len(to_create) - 1 if send_in_app else None))

    created: list[Notification] = []
    if to_create:
        try:
            created = Notification.objects.bulk_create(to_create)
        except Exception:
            logger.exception('bulk_create failed for notification type %s', notification_type)

    for email, idx in email_recipients:
        notification_id = created[idx].id if (idx is not None and idx < len(created)) else None
        _enqueue_email(
            to=email,
            subject=email_subject or title,
            body=email_body or body,
            notification_id=notification_id,
        )

    return created


def _enqueue_email(to: str, subject: str, body: str, notification_id: int | None = None):
    """
    Enqueue an email via Google Cloud Tasks (HTTP push).
    Falls back to synchronous send when USE_CLOUD_TASKS is False (local dev).
    """
    if not getattr(settings, 'USE_CLOUD_TASKS', True):
        from core.emails import send_plain_email
        try:
            send_plain_email(subject=subject, body=body, to=to)
            if notification_id:
                from django.utils import timezone
                Notification.objects.filter(pk=notification_id).update(
                    is_emailed=True,
                    emailed_at=timezone.now(),
                )
        except Exception:
            logger.exception('Synchronous email failed to %s', to)
        return

    try:
        from notifications.tasks import enqueue_send_email
        enqueue_send_email(
            to=to,
            subject=subject,
            body=body,
            notification_id=notification_id,
        )
    except Exception:
        logger.exception('Failed to enqueue email task to %s', to)
