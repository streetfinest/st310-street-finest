# Street Finest Academic Hub — V4.0 staged development build

**Not deployed to production. Do not merge directly into GitHub `main`.**

## Final agreed student experience
- Universal Street Finest Academic Hub homepage with four service cards: Course Registrations, Academic Hub, Announcements and Opportunities.
- Course Registrations lists course portals created and published by Master Admin plus **My Registrations**.
- My Registrations asks the student to select a course and provide registration number, surname, first name and optional third/second name before showing a matching record. Otherwise it shows a generic not-found message, without confirming whether an ID exists.
- Once found, the course record shows its seminar and (if permitted) one-time selection / shift-request action. One student cannot occupy two seminar groups in the same course.
- Academic Hub presents searchable course cards and downloadable resources; Announcements and Opportunities are admin-managed.

## Final agreed admin experience
- Course Registration Manager: create, configure, publish, close, archive, show/hide, inspect, correct (with audit log), export Excel and seminar worksheets.
- Academic Hub Manager: publish course cards, upload resources (PDF, PPTX, DOCX, XLSX, PNG, JPG), control visibility, edit titles.
- Announcements and Opportunities managers: create, edit, publish/unpublish.
- Homepage Manager: set title/subtitle, show/hide/reorder the four service cards while preserving the core branding assets.
- Shift Requests Manager, Reports/Exports and separate protected ST310 Legacy Tools.

## UI lock
- This is a responsive website, **not** an image inside a phone, phone bezel, or mockup. It fills the actual mobile browser screen.
- Retains UDSM crest + gateway photo, navy/gold academic plaque, silver frosted-glass main panel, curved Street Finest footer.
- A smartphone device frame used in prior concept art is **not** part of HTML or CSS.

## Data protection and honest limitations
- No production data or secrets are bundled; legacy ST310 `students`, `cr_accounts`, programme approvals, audit history and seminar shifts remain in their original database tables. ST310 is accessed at `/st310`.
- Existing ST310 CR approval and official submission exports still use V3.3 screens; newly created V4 course portals do **not** yet implement separate CR accounts/approvals.
- Registration-number + full-name matching alone is weak identity proof. Short-lived tokens and basic lookup rate limits help, but proper student sign-in / OTP is advised before public rollout of sensitive actions.
- Real off-site production backup and staging mobile/desktop test are required **before** production deployment; migration tests only used synthetic data.
- Materials require persistent storage, recommended `HUB_UPLOAD_DIR=/var/data/hub_uploads`.
