Social network
==============

*Murmur*: posts, likes, follows, profiles and a home timeline.

.. code-block:: text

   social-network/
   ├── app.py            # composition root
   ├── settings.py       # NETWORK_NAME, MAX_POST_LENGTH, DATABASE_URL
   ├── models/           # database.py, member.py (Member, Follow), post.py (Post, Like)
   ├── services/         # social.py (SocialService), seed.py
   └── views/
       ├── components/   # shell, composer, post_card, who_to_follow
       ├── pages/        # home, explore, profile, account
       └── styles/

1. Association tables
---------------------

.. literalinclude:: ../../examples/social-network/models/member.py
   :pyobject: Follow

.. literalinclude:: ../../examples/social-network/models/post.py
   :pyobject: Like

Composite primary keys make "follow twice" and "like twice" impossible at the database level.

2. Timelines in a fixed number of queries
-----------------------------------------

.. literalinclude:: ../../examples/social-network/services/social.py
   :pyobject: SocialService.timeline

.. literalinclude:: ../../examples/social-network/services/social.py
   :pyobject: SocialService._views

Authors come in one ``selectinload`` query, like counts in one ``GROUP BY``, and your likes in
one ``IN`` query, whether the timeline has 5 posts or 500. The test suite counts the SQL
statements to prove it.

3. Local updates
----------------

.. literalinclude:: ../../examples/social-network/views/components/post_card.py
   :pyobject: PostCard

Liking re-renders only that card: its state starts from the props in ``mount()`` and then
follows the server's answer.

4. A live character counter
---------------------------

.. literalinclude:: ../../examples/social-network/views/components/composer.py
   :pyobject: Composer

The counter follows your typing and the button enables only for a valid post. The server still
validates on submit, because it never trusts the browser.

5. Callbacks between components
-------------------------------

.. literalinclude:: ../../examples/social-network/views/pages/home.py
   :pyobject: Home

``Composer(posted=self.reload)`` and ``WhoToFollow(followed=self.reload)`` tell the page to
reload the timeline.
