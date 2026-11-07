"""
seed.py - Populate the database with realistic sample data for testing.

SAFE TO RUN ON AN EXISTING DATABASE — it will NOT drop or overwrite
existing records.  Skills and users are only created if they do not
already exist (checked by email / skill name).

Run with: python seed.py
"""
from app import create_app
from app.models import db, User, Skill, ExchangeRequest, Message, Review, Notification
from sqlalchemy import text

app = create_app('development')

SKILLS_DATA = [
    # (name, category, description, icon)
    ('Python Programming',  'Programming',    'Core Python: OOP, data structures, scripting',         'fa-python'),
    ('JavaScript',          'Web Development','ES6+, DOM, async/await, frontend development',          'fa-js'),
    ('React.js',            'Web Development','Component-based UI with React and hooks',               'fa-react'),
    ('Data Science',        'Data Science',   'Pandas, NumPy, data analysis and visualisation',        'fa-chart-bar'),
    ('Machine Learning',    'Data Science',   'Scikit-learn, model training, evaluation',              'fa-brain'),
    ('UI/UX Design',        'Design',         'Figma, user research, wireframing, prototyping',        'fa-paint-brush'),
    ('Guitar',              'Music',          'Acoustic and electric guitar, chords, scales',          'fa-guitar'),
    ('Spanish',             'Language',       'Conversational Spanish, grammar, vocabulary',           'fa-language'),
    ('Photography',         'Photography',    'DSLR/mirrorless, composition, editing in Lightroom',    'fa-camera'),
    ('Creative Writing',    'Writing',        'Fiction, poetry, narrative techniques',                 'fa-pen'),
    ('Calculus',            'Mathematics',    'Differential and integral calculus',                    'fa-calculator'),
    ('Digital Marketing',   'Business',       'SEO, social media, content strategy',                  'fa-bullhorn'),
    ('Graphic Design',      'Design',         'Adobe Photoshop, Illustrator, typography',              'fa-palette'),
    ('Public Speaking',     'Business',       'Presentations, debate, communication skills',           'fa-microphone'),
    ('Video Editing',       'Design',         'Premiere Pro, After Effects, storytelling',             'fa-film'),
    ('Yoga & Meditation',   'Sports',         'Hatha yoga, breathing techniques, mindfulness',         'fa-om'),
    ('SQL & Databases',     'Programming',    'PostgreSQL, MySQL, query optimisation',                 'fa-database'),
    ('Hindi',               'Language',       'Spoken Hindi, grammar, script reading',                 'fa-language'),
    ('Cooking',             'Cooking',        'Vegetarian and non-vegetarian Indian cuisine',          'fa-utensils'),
    ('Drawing & Sketching', 'Art & Craft',    'Portrait, landscape, pencil and charcoal',              'fa-pencil-alt'),
]

STUDENTS = [
    # (full_name, email, password, college, branch, year, bio, experience)
    ('Arjun Sharma',    'arjun@iitb.edu',    'pass123', 'IIT Bombay',      'Computer Science', '3rd Year', 'Passionate coder who loves open source and hackathons.', 'Intermediate'),
    ('Priya Patel',     'priya@nit.edu',     'pass123', 'NIT Surat',       'Electronics',      '2nd Year', 'Electronics student with a love for music and photography.', 'Beginner'),
    ('Rohan Gupta',     'rohan@bits.edu',    'pass123', 'BITS Pilani',     'Data Science',     '4th Year', 'Data nerd building ML models for fun.', 'Expert'),
    ('Sneha Iyer',      'sneha@vit.edu',     'pass123', 'VIT Vellore',     'Design',           '2nd Year', 'Designer who believes good design changes lives.', 'Intermediate'),
    ('Kavya Menon',     'kavya@nit.edu',     'pass123', 'NIT Calicut',     'Mechanical',       '3rd Year', 'Engineer who dabbles in writing and yoga.', 'Beginner'),
    ('Aditya Verma',    'aditya@iitd.edu',   'pass123', 'IIT Delhi',       'Mathematics',      '4th Year', 'Math enthusiast, loves teaching calculus.', 'Expert'),
    ('Meera Krishnan',  'meera@psg.edu',     'pass123', 'PSG College',     'Business Admin',   '1st Year', 'Aspiring entrepreneur interested in digital marketing.', 'Beginner'),
    ('Vikram Singh',    'vikram@manipal.edu','pass123', 'Manipal University','CS',             '3rd Year', 'Full-stack dev building startup products.', 'Expert'),
]

# teaching_skill_indices, learning_skill_indices (0-based into SKILLS_DATA)
STUDENT_SKILLS = [
    # Arjun: teaches Python, JS; wants to learn Guitar, Photography
    ([0,1],  [6,8]),
    # Priya: teaches Guitar, Photography; wants to learn Python, Design
    ([6,8],  [0,5]),
    # Rohan: teaches Data Science, ML; wants to learn Spanish, Public Speaking
    ([3,4],  [7,13]),
    # Sneha: teaches UI/UX, Graphic Design, Video; wants to learn Python, JS
    ([5,12,14],[0,1]),
    # Kavya: teaches Yoga, Cooking; wants to learn ML, Writing
    ([15,18],[4,9]),
    # Aditya: teaches Calculus, SQL; wants to learn Guitar, Cooking
    ([10,16],[6,18]),
    # Meera: teaches Digital Marketing, Public Speaking; wants to learn Python, Graphic Design
    ([11,13],[0,12]),
    # Vikram: teaches Python, React, JS; wants to learn UI/UX, Photography
    ([0,2,1],[5,8]),
]


def seed():
    with app.app_context():
        # ── SAFETY: never drop or recreate tables ────────────────
        # db.create_all() only creates tables that don't exist yet.
        # It never modifies or deletes existing rows.
        db.create_all()

        print("\nSkillSwap — Safe Seed (existing data is preserved)\n")

        existing_users  = User.query.count()
        existing_skills = Skill.query.count()
        print(f"  Current DB state: {existing_users} users, {existing_skills} skills")

        # ── Skills ────────────────────────────────────────────────
        # Only insert skills whose name doesn't already exist.
        print("\nSeeding skills (skipping duplicates)...")
        skill_objs = []
        skills_added = 0
        for name, cat, desc, icon in SKILLS_DATA:
            existing = Skill.query.filter_by(name=name).first()
            if existing:
                skill_objs.append(existing)
            else:
                s = Skill(name=name, category=cat, description=desc, icon=icon)
                db.session.add(s)
                db.session.flush()
                skill_objs.append(s)
                skills_added += 1
        db.session.flush()
        print(f"  Added {skills_added} new skills, {len(SKILLS_DATA) - skills_added} already existed.")

        # ── Admin ─────────────────────────────────────────────────
        if not User.query.filter_by(email='admin@skillswap.com').first():
            print("Creating admin user...")
            admin = User(
                full_name='Admin User',
                email='admin@skillswap.com',
                college='SkillSwap HQ',
                branch='Administration',
                year='N/A',
                bio='Platform administrator.',
                is_admin=True
            )
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.flush()
            print("  Admin created.")
        else:
            print("  Admin already exists — skipped.")

        # ── Students ──────────────────────────────────────────────
        print("\nSeeding students (skipping existing accounts)...")
        student_objs = []
        students_added = 0
        for i, (name, email, pw, college, branch, year, bio, exp) in enumerate(STUDENTS):
            existing_user = User.query.filter_by(email=email).first()
            if existing_user:
                student_objs.append(existing_user)
                continue   # skip — do NOT overwrite existing account

            u = User(
                full_name=name, email=email,
                college=college, branch=branch, year=year,
                bio=bio, experience=exp
            )
            u.set_password(pw)
            db.session.add(u)
            db.session.flush()

            # Assign skills only for newly created users
            teach_ids, learn_ids = STUDENT_SKILLS[i]
            for ti in teach_ids:
                db.session.execute(
                    text('INSERT OR IGNORE INTO user_teaching_skills '
                         '(user_id, skill_id, proficiency) VALUES (:u,:s,:p)'),
                    {'u': u.id, 's': skill_objs[ti].id, 'p': exp}
                )
            for li in learn_ids:
                db.session.execute(
                    text('INSERT OR IGNORE INTO user_learning_skills '
                         '(user_id, skill_id) VALUES (:u,:s)'),
                    {'u': u.id, 's': skill_objs[li].id}
                )
            student_objs.append(u)
            students_added += 1

        db.session.flush()
        print(f"  Added {students_added} new students, "
              f"{len(STUDENTS) - students_added} already existed.")

        # ── Sample exchanges / messages only if both parties are NEW ─
        # We only create sample relationships between freshly created accounts
        # to avoid duplicate exchange requests between existing users.
        if students_added == len(STUDENTS):
            print("\nSeeding sample exchanges, messages and reviews...")

            r1 = ExchangeRequest(
                sender_id=student_objs[0].id, receiver_id=student_objs[1].id,
                skill_requested_id=skill_objs[6].id, skill_offered_id=skill_objs[0].id,
                message="Hi Priya! I'd love to learn guitar from you. I can teach Python in return.",
                status='accepted'
            )
            r2 = ExchangeRequest(
                sender_id=student_objs[2].id, receiver_id=student_objs[3].id,
                skill_requested_id=skill_objs[5].id, skill_offered_id=skill_objs[3].id,
                message="Hey Sneha! Interested in swapping Data Science for UI/UX skills?",
                status='pending'
            )
            r3 = ExchangeRequest(
                sender_id=student_objs[7].id, receiver_id=student_objs[3].id,
                skill_requested_id=skill_objs[5].id, skill_offered_id=skill_objs[0].id,
                message="Let's exchange Python for design skills!",
                status='completed'
            )
            r4 = ExchangeRequest(
                sender_id=student_objs[5].id, receiver_id=student_objs[4].id,
                skill_requested_id=skill_objs[18].id, skill_offered_id=skill_objs[10].id,
                message="Would love to learn cooking! I can teach calculus.",
                status='accepted'
            )
            for r in [r1, r2, r3, r4]:
                db.session.add(r)
            db.session.flush()

            msgs = [
                Message(sender_id=student_objs[0].id, receiver_id=student_objs[1].id,
                        content="Hi Priya! Really excited to start our skill exchange.", is_read=True),
                Message(sender_id=student_objs[1].id, receiver_id=student_objs[0].id,
                        content="Me too Arjun! When are you free for the first session?", is_read=True),
                Message(sender_id=student_objs[0].id, receiver_id=student_objs[1].id,
                        content="How about Saturday afternoon at 3pm?", is_read=True),
                Message(sender_id=student_objs[1].id, receiver_id=student_objs[0].id,
                        content="Perfect! I'll bring my guitar. Can you bring your laptop for Python?",
                        is_read=False),
            ]
            for m in msgs:
                db.session.add(m)

            rv1 = Review(reviewer_id=student_objs[7].id, reviewee_id=student_objs[3].id,
                         exchange_id=r3.id, rating=5,
                         feedback="Sneha is an amazing design teacher! Highly recommend!")
            rv2 = Review(reviewer_id=student_objs[3].id, reviewee_id=student_objs[7].id,
                         exchange_id=r3.id, rating=5,
                         feedback="Vikram explained Python concepts so clearly. Great exchange!")
            db.session.add(rv1)
            db.session.add(rv2)

            notif1 = Notification(user_id=student_objs[1].id,
                                   title='Arjun Sharma accepted your exchange!',
                                   body='You can now start messaging each other.',
                                   link='/exchanges/', icon='fa-handshake', is_read=False)
            notif2 = Notification(user_id=student_objs[3].id,
                                   title='New exchange request from Rohan Gupta',
                                   body='Interested in swapping Data Science for UI/UX skills?',
                                   link='/exchanges/', icon='fa-envelope', is_read=False)
            db.session.add(notif1)
            db.session.add(notif2)
        else:
            print("\n  Sample exchanges/messages skipped "
                  "(some seed students already existed — avoiding duplicates).")

        db.session.commit()
        print("\n✓ Seed completed. No existing data was modified.\n")
        print("── Login credentials ──────────────────────────")
        print("Admin:    admin@skillswap.com  /  admin123")
        for name, email, pw, *_ in STUDENTS:
            print(f"Student:  {email:<28} /  {pw}")
        print("───────────────────────────────────────────────")


if __name__ == '__main__':
    seed()
