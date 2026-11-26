import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CurrentUiContractsTest(unittest.TestCase):
    def read(self, relative_path):
        return (ROOT / relative_path).read_text(encoding="utf-8")

    def test_login_and_identity_pages_use_current_theme(self):
        login = self.read("templates/login.html")
        identity = self.read("templates/link_account.html")
        self.assertIn("{% extends 'auth_base.html' %}", login)
        self.assertIn("{% extends 'auth_base.html' %}", identity)
        self.assertNotIn("eva-", login.lower())
        self.assertNotIn("eva-", identity.lower())
        self.assertIn('id="school-email"', login)
        self.assertIn('id="pin-login"', login)
        self.assertIn("auto_submit=true", login)
        self.assertNotIn('<details id="school-email"', login)
        self.assertNotIn('<details id="pin-login"', login)
        self.assertNotIn("auth-migration-notice", login)
        self.assertEqual(login.count("url_for('signup'"), 1)
        self.assertIn("← 6자리 PIN으로 로그인", login)

    def test_guest_auth_shell_is_isolated_and_clean(self):
        auth = self.read("templates/auth_base.html")
        css = self.read("static/lms_auth.css")
        signup = self.read("templates/signup.html")
        self.assertIn("{% set lms_isolated_auth = not session.user_role %}", auth)
        self.assertIn("{% extends 'lms_base.html' %}", auth)
        self.assertIn("auth-brand", auth)
        self.assertIn('body.lms-isolated-auth[data-lms-page="auth"]', css)
        self.assertIn("max-width:440px", css)
        self.assertNotIn("auth-secondary-cta", css)
        self.assertIn(".lms-result-portal", css)
        self.assertIn(".portal-confirm-dialog", css)
        self.assertIn("legacy_signup", signup)
        self.assertIn("auth-steps", signup)

    def test_auth_digit_inputs_use_shared_progressive_enhancement(self):
        auth = self.read("templates/auth_base.html")
        macro = self.read("templates/_auth_code.html")
        css = self.read("static/lms_auth.css")
        script = self.read("static/auth_code_boxes.js")
        self.assertIn('<script defer src="{{ url_for(\'static\', filename=\'auth_code_boxes.js\') }}">', auth)
        self.assertIn('data-auth-code-controls hidden', macro)
        self.assertIn('data-auto-submit="true"', macro)
        self.assertIn("auto_submit=false", macro)
        self.assertIn("maybeAutoSubmit", script)
        self.assertIn('data-digit-mask=', macro)
        self.assertIn('range(1, 7)', macro)
        self.assertIn('data-auth-code-toggle aria-pressed="false"', macro)
        self.assertIn('grid-template-columns:repeat(6,minmax(0,1fr))', css)
        self.assertIn('auth-code-enhanced', script)
        for template, fields in (
            ("templates/login.html", ("login-code", "login-pin")),
            ("templates/signup.html", ("signup-pin",)),
            ("templates/account_password.html", ("new-pin", "confirm-pin")),
        ):
            page = self.read(template)
            for field in fields:
                self.assertIn(f"'{field}'", page)
            self.assertIn("import auth_code", page)

    def test_unlinked_kakao_flow_leads_with_signup(self):
        identity = self.read("templates/link_account.html")
        self.assertIn("회원가입을<br>진행할게요", identity)
        self.assertIn('name="action" value="create"', identity)
        self.assertIn("이미 동아리 명부에 등록되어 있어요", identity)

    def test_school_email_inputs_share_a_responsive_suffix(self):
        for template in ("login", "signup", "officer_handover_form"):
            self.assertIn("import knu_email_input", self.read(f"templates/{template}.html"))
        macro = self.read("templates/_knu_email_input.html")
        self.assertIn('type="text" inputmode="email"', macro)
        self.assertIn('data-knu-email-input', macro)
        self.assertIn('aria-hidden="true">@knu.ac.kr</span>', macro)
        for stylesheet in ("lms_auth.css", "lms_engagement.css"):
            self.assertIn("@import url('knu_email.css');", self.read(f"static/{stylesheet}"))
        self.assertIn(".knu-email-group:focus-within", self.read("static/knu_email.css"))

    def test_seminar_reviews_are_managed_in_seminar_screen(self):
        seminars = self.read("templates/admin_seminars.html")
        engagement = self.read("templates/admin_engagement.html")
        self.assertIn("macro review_panel(seminar_session)", seminars)
        self.assertIn("{{ review_panel(mon) }}", seminars)
        self.assertIn("{{ review_panel(thu) }}", seminars)
        self.assertIn("review-form-status", seminars)
        self.assertNotIn("후기 모아보기", seminars)
        self.assertNotIn("세미나 후기 링크 열기", engagement)

    def test_html_response_gets_a_light_first_paint(self):
        app_source = self.read("app.py")
        self.assertIn('data-critical-theme="wood"', app_source)
        self.assertIn('data-wood-theme="1"', app_source)
        self.assertIn('<meta name="color-scheme" content="light">', app_source)
        self.assertIn("body{background-color:#FAF6EC}", app_source)

    def test_topic_submission_has_readable_current_theme(self):
        topic = self.read("templates/topic_submit.html")
        stylesheet = self.read("static/lms_topics.css")
        self.assertIn("{% extends 'lms_base.html' %}", topic)
        self.assertIn("filename='lms_topics.css'", topic)
        self.assertIn("topic-hero", topic)
        self.assertIn(".lms-topics .topic-author", stylesheet)
        self.assertIn(".lms-topics label{display:block", stylesheet)
        self.assertNotIn("opacity:0.7", topic)

    def test_full_documents_load_theme_in_head_without_tailwind_cdn(self):
        templates = list((ROOT / "templates").glob("*.html"))
        for template in templates:
            source = template.read_text(encoding="utf-8")
            self.assertNotIn("cdn.tailwindcss.com", source, template.name)
            self.assertNotIn("tailwind.config =", source, template.name)
            if "<html" in source.lower() and "</head>" in source.lower():
                head = source.split("</head>", 1)[0]
                if 'name="app-layout" content="canvas"' in head:
                    self.assertIn("filename='lms.css'", head, template.name)
                    self.assertIn('name="color-scheme" content="light"', head, template.name)
                elif 'name="app-layout" content="public-landing"' in head:
                    # The external landing page ships its own self-contained stylesheet.
                    self.assertIn("filename='public_landing.css'", head, template.name)
                    self.assertIn('name="color-scheme" content="light"', head, template.name)
                else:
                    self.assertIn("{% include '_app_theme_head.html' %}", head, template.name)

        tailwind_head = self.read("templates/_tailwind_head.html")
        self.assertIn("filename='tailwind.css'", tailwind_head)
        self.assertIn('data-tailwind-build="3.4.17"', tailwind_head)

    def test_legacy_neon_theme_is_gone_from_templates(self):
        legacy_tokens = (
            "Orbitron", "#00FF7F", "#6A0DAD", "#1A1A1A", "#2D2D2D",
            "#1F1F1F", "#232323", "#3A3A3A", "#ADFF2F",
            "rgba(0, 255, 127", "rgba(0,255,127",
            "rgba(106, 13, 173", "rgba(106,13,173",
        )
        for template in (ROOT / "templates").glob("*.html"):
            source = template.read_text(encoding="utf-8")
            for token in legacy_tokens:
                self.assertNotIn(token, source, f"{token} remains in {template.name}")

    def test_now_no_longer_offers_retired_site_vote(self):
        engagement = self.read("engagement.py")
        self.assertNotIn('url_for("seminar_vote_page", token=', engagement)
        self.assertNotIn('url_for("seminar_vote", token=', engagement)
        self.assertIn('카카오톡에서 진행합니다', engagement)

    def test_legacy_genres_are_not_shown_in_seminar_activity(self):
        member = self.read("templates/records_member_profile.html")
        seminars = self.read("templates/records_seminars.html")
        detail = self.read("templates/records_seminar_detail.html")
        self.assertNotIn("s.genre", member)
        self.assertNotIn("genreFilter", seminars)
        self.assertNotIn("genreSelect", detail)

    def test_seminar_detail_imports_its_shared_genre_script(self):
        detail = self.read("templates/records_seminar_detail.html")
        self.assertIn(
            "{% from '_records_base.html' import records_header, records_nav, genre_script %}",
            detail,
        )
        self.assertIn("{{ genre_script() }}", detail)

    def test_book_cards_have_a_clear_action(self):
        books = self.read("templates/book_suggestions.html")
        self.assertIn('class="eg-suggestion-row"', books)
        self.assertIn("url_for('book_suggestion_detail', suggestion_id=item.id)", books)
        self.assertIn('class="eg-row-action">같이 읽고 싶어요', books)

    def test_semester_members_lead_with_current_roster_and_seminar_dates(self):
        roster = self.read("templates/admin_term_members.html")
        schedule = self.read("templates/admin_schedule_editor.html")
        self.assertIn("data-filter=\"assigned\" aria-pressed=\"true\"", roster)
        self.assertIn("직전 활동자 중 미포함", roster)
        self.assertIn("다른 회원 찾기", roster)
        self.assertNotIn("기존 활성 회원 불러오기", roster)
        for source in (roster, schedule):
            self.assertIn("첫 세미나 날짜", source)
            self.assertIn("마지막 세미나 날짜", source)

    def test_retired_seminar_vote_share_link_ui_is_removed(self):
        dashboard = self.read("templates/admin_dashboard.html")
        term = self.read("templates/admin_seminar_term.html")
        app_source = self.read("app.py")
        self.assertNotIn("copySeminarLink", dashboard)
        self.assertNotIn("term.share_url", dashboard)
        self.assertNotIn("data.share_url", dashboard)
        self.assertNotIn("copyShareLink", term)
        self.assertNotIn("{{ share_url }}", term)
        self.assertIn("seminar_vote_retired.html", app_source)

    def test_favicon_partial_includes_pwa_apple_touch_icon(self):
        favicon = self.read("templates/_favicon.html")
        self.assertIn('rel="apple-touch-icon"', favicon)
        self.assertIn("icons/icon-192.png", favicon)

    def test_og_preview_image_is_resized_and_lightweight(self):
        from PIL import Image
        og_path = ROOT / "static" / "og" / "club-preview-v2.png"
        self.assertTrue(og_path.exists())
        self.assertLessEqual(og_path.stat().st_size, 350_000)
        with Image.open(og_path) as img:
            self.assertEqual(img.format, "PNG")
            self.assertEqual(img.size, (1200, 600))

    def test_records_members_template_has_clean_utf8_and_inactive_confirm(self):
        members = self.read("templates/records_members.html")
        self.assertNotIn("&#xD69F;", members)
        self.assertIn("세미나·발제 횟수는 과거 기록에 저장된 이름 기준입니다.", members)
        self.assertIn("next==='inactive'&&!confirm(", members)

    def test_board_post_and_list_security_and_moderation_contracts(self):
        post_html = self.read("templates/board_post.html")
        list_html = self.read("templates/board_list.html")
        self.assertIn('target="_blank" rel="noopener noreferrer"', post_html)
        self.assertRegex(post_html, r"deleteComment\([^)]*\)[\s\S]*if\s*\(!r\.ok\)")
        self.assertIn("delete-link-review", list_html)
        self.assertIn("session.user_role in ['admin', 'officer']", list_html)

    def test_wave4bc_ui_tokens_and_consolidated_navigation_contracts(self):
        base = self.read("templates/lms_base.html")
        nav = self.read("templates/_lms_navigation.html")
        tokens = self.read("static/lms_ui_tokens.css")
        self.assertIn("filename='lms_ui_tokens.css'", base)
        self.assertIn('class="lms-bell-btn"', base)
        self.assertIn('class="lms-mobile-bell"', base)
        for token in ("--ui-accent:", "--ui-surface:", "--ui-ink:", ".ui-tabs", ".ui-page-header"):
            self.assertIn(token, tokens)
        self.assertNotIn('data-lms-panel="lms-notifications"', nav)
        self.assertNotIn("<span>운영진 위키</span>", nav)
        self.assertNotIn("<span>이용안내</span>", nav)
        for dark_free_template in (
            "templates/admin_dashboard.html",
            "templates/admin_special_events.html",
            "templates/admin_special_event_detail.html",
            "templates/admin_seminar_rooms.html",
            "templates/admin_attendance_matrix.html",
            "templates/admin_seminar_term.html",
            "templates/_lms_operations_session_card.html",
            "templates/admin_topic_view.html",
            "templates/admin_boards.html",
        ):
            src = self.read(dark_free_template)
            for forbidden in ("bg-gray-", "text-gray-", "border-gray-", "bg-blue-"):
                self.assertNotIn(forbidden, src, f"{forbidden} remains in {dark_free_template}")


if __name__ == "__main__":
    unittest.main()
