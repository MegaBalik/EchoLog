from django.contrib import admin

from .models import Batch, Contact, GmailSyncState, Recipient


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ('display_name_admin', 'company', 'email', 'country', 'domain', 'do_not_contact', 'bounced')
    search_fields = ('name', 'company', 'email', 'country', 'domain', 'website', 'note')
    list_filter = ('country', 'do_not_contact', 'bounced')
    readonly_fields = ('created_at', 'updated_at')

    @admin.display(description='Name', ordering='name')
    def display_name_admin(self, obj):
        return obj.display_name


@admin.register(Batch)
class BatchAdmin(admin.ModelAdmin):
    list_display = ('name', 'status', 'created_at', 'started_at', 'daily_limit')
    list_filter = ('status',)
    search_fields = ('name', 'subject')


@admin.register(Recipient)
class RecipientAdmin(admin.ModelAdmin):
    list_display = ('contact', 'batch', 'status', 'hope', 'sent_at', 'replied_at')
    list_filter = ('status', 'hope', 'batch', 'contact__country')
    search_fields = ('contact__name', 'contact__company', 'contact__email', 'contact__domain', 'batch__name')
    raw_id_fields = ('contact', 'batch')


admin.site.register(GmailSyncState)
