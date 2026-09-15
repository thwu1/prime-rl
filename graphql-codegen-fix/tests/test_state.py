
import subprocess
import re
import os
import textwrap


GENERATED_PATH = '/app/generated/types.ts'


def extract_type(content: str, type_name: str) -> str | None:
    """Extract a full type declaration block by name, handling nested braces."""
    pattern = rf'export type {re.escape(type_name)}\b'
    match = re.search(pattern, content)
    if not match:
        return None
    start = match.start()
    i = start
    depth = 0
    found_open = False
    while i < len(content):
        ch = content[i]
        if ch == '{':
            depth += 1
            found_open = True
        elif ch == '}':
            depth -= 1
        elif ch == ';' and depth == 0 and (found_open or i > start + 15):
            return content[start : i + 1]
        i += 1
    return content[start:]


def normalize(s: str) -> str:
    """Collapse all whitespace into single spaces."""
    return re.sub(r'\s+', ' ', s).strip()


class TestCodegenOutput:
    content: str

    @classmethod
    def setup_class(cls):
        """Read the generated output produced by test.sh."""
        assert os.path.exists(GENERATED_PATH), (
            f'Generated file not found at {GENERATED_PATH}. '
            'Run npx tsx /app/src/codegen.ts first.'
        )
        with open(GENERATED_PATH, 'r') as f:
            cls.content = f.read()
        assert len(cls.content) > 100, 'Generated file is too small'

    # ------------------------------------------------------------------
    # Bug 1: Fragment spreads must be resolved
    # ------------------------------------------------------------------
    def test_fragment_spread_resolution(self):
        """Fragment spreads like ...UserFields must inline all fragment fields."""
        user_profile = extract_type(self.content, 'UserProfileQuery')
        assert user_profile is not None, 'UserProfileQuery type not found'
        norm = normalize(user_profile)
        assert 'username: string' in norm, (
            'Fragment fields not resolved: "username" missing from UserProfileQuery. '
            'The ...UserFields spread must be resolved to include fragment fields.'
        )
        assert 'email: string' in norm, (
            'Fragment fields not resolved: "email" missing from UserProfileQuery.'
        )
        assert 'status: Status' in norm, (
            'Fragment fields not resolved: "status" missing from UserProfileQuery.'
        )

    def test_fragment_type_standalone(self):
        """Fragment type definitions should contain their fields."""
        frag = extract_type(self.content, 'UserFieldsFragment')
        assert frag is not None, 'UserFieldsFragment type not found'
        norm = normalize(frag)
        assert 'username: string' in norm
        assert 'status: Status' in norm

    # ------------------------------------------------------------------
    # Bug 2: Discriminated unions for inline fragments on unions/interfaces
    # ------------------------------------------------------------------
    def test_discriminated_union_search(self):
        """Inline fragments on union types must produce a discriminated union with __typename."""
        search = extract_type(self.content, 'SearchContentQuery')
        assert search is not None, 'SearchContentQuery type not found'
        norm = normalize(search)
        assert '__typename:' in norm, (
            'Union type missing __typename discriminator in SearchContentQuery.'
        )
        for tn in ('User', 'Post', 'Comment'):
            assert f"'{tn}'" in norm or f'"{tn}"' in norm, (
                f"Union type missing '{tn}' branch in SearchContentQuery."
            )

    def test_discriminated_union_node(self):
        """Inline fragments on interface types must produce a discriminated union."""
        node_query = extract_type(self.content, 'GetNodeQuery')
        assert node_query is not None, 'GetNodeQuery type not found'
        norm = normalize(node_query)
        assert '__typename:' in norm, (
            'Interface type missing __typename discriminator in GetNodeQuery.'
        )

    # ------------------------------------------------------------------
    # Bug 3: Field aliases
    # ------------------------------------------------------------------
    def test_field_aliases(self):
        """Fields with aliases must use the alias name as the type key."""
        dashboard = extract_type(self.content, 'DashboardDataQuery')
        assert dashboard is not None, 'DashboardDataQuery type not found'
        norm = normalize(dashboard)
        assert 'currentUser:' in norm, (
            "Alias 'currentUser' not used (field is still named 'user')."
        )
        assert 'displayName:' in norm, (
            "Alias 'displayName' not used (field is still named 'username')."
        )
        assert 'emailAddress:' in norm, (
            "Alias 'emailAddress' not used (field is still named 'email')."
        )
        assert 'memberSince:' in norm, (
            "Alias 'memberSince' not used (field is still named 'createdAt')."
        )
        assert 'featuredPost:' in norm, (
            "Alias 'featuredPost' not used (field is still named 'post')."
        )
        assert 'headline:' in norm, (
            "Alias 'headline' not used (field is still named 'title')."
        )

    # ------------------------------------------------------------------
    # Bug 4: @skip / @include directives make fields optional
    # ------------------------------------------------------------------
    def test_conditional_directives(self):
        """Fields with @skip or @include must be optional (have '?')."""
        feed = extract_type(self.content, 'FeedWithOptionsQuery')
        assert feed is not None, 'FeedWithOptionsQuery type not found'
        norm = normalize(feed)
        assert 'author?:' in norm, (
            "Field 'author' with @include directive should be optional (author?:)."
        )
        assert 'tags?:' in norm, (
            "Field 'tags' with @skip directive should be optional (tags?:)."
        )
        # Non-conditional fields must NOT be optional
        assert re.search(r'\btitle\b\s*:', norm) and 'title?:' not in norm, (
            "Field 'title' (no directive) should not be optional."
        )

    # ------------------------------------------------------------------
    # Bug 5: @oneOf input types
    # ------------------------------------------------------------------
    def test_oneOf_input_type(self):
        """@oneOf input types must generate exclusive unions with 'never' fields."""
        user_lookup = extract_type(self.content, 'UserLookupInput')
        assert user_lookup is not None, 'UserLookupInput type not found'
        norm = normalize(user_lookup)
        assert 'never' in norm, (
            "@oneOf input type should have 'never' for non-active fields."
        )
        assert '|' in norm, (
            '@oneOf input type should be a union (contain "|").'
        )

    # ------------------------------------------------------------------
    # Bug 6: List nullability
    # ------------------------------------------------------------------
    def test_scalar_list_nullability(self):
        """[String!]! must produce Array<string>, not Array<string | null>."""
        post_summary = extract_type(self.content, 'PostSummaryFragment')
        assert post_summary is not None, 'PostSummaryFragment type not found'
        norm = normalize(post_summary)
        assert 'tags: Array<string>' in norm, (
            f'[String!]! should generate "Array<string>", got: {norm}'
        )
        assert 'Array<string | null>' not in norm, (
            'tags should not have nullable inner items for [String!]!.'
        )

    def test_object_list_nullability(self):
        """[PostEdge!]! must produce Array<{...}>, not Array<{...} | null>."""
        user_profile = extract_type(self.content, 'UserProfileQuery')
        assert user_profile is not None
        norm = normalize(user_profile)
        # edges: [PostEdge!]! — items should NOT be nullable
        # After fixing, the pattern should be Array<{ ... cursor: string; }>
        # not Array<{ ... cursor: string; } | null>
        edges_idx = norm.find('edges:')
        assert edges_idx != -1, 'edges field not found in UserProfileQuery'
        # Extract the text from 'edges:' up to its closing semicolon
        after_edges = norm[edges_idx:]
        # Find balanced end: count depth from first '<'
        depth = 0
        end = 0
        for i, ch in enumerate(after_edges):
            if ch == '<':
                depth += 1
            elif ch == '>':
                depth -= 1
                if depth == 0:
                    end = i
                    break
        edges_type = after_edges[: end + 1]
        assert '| null>' not in edges_type, (
            '[PostEdge!]! items should not be nullable. '
            f'Got: {edges_type}'
        )

    # ------------------------------------------------------------------
    # TypeScript compilation
    # ------------------------------------------------------------------
    def test_typescript_compilation(self):
        """Generated types.ts must compile with tsc --noEmit --strict."""
        result = subprocess.run(
            [
                'npx', 'tsc', '--noEmit', '--strict',
                '--target', 'ES2022',
                '--module', 'node16',
                '--moduleResolution', 'node16',
                GENERATED_PATH,
            ],
            cwd='/app',
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f'TypeScript compilation failed:\n{result.stdout}\n{result.stderr}'
        )

    # ------------------------------------------------------------------
    # Enum types
    # ------------------------------------------------------------------
    def test_enum_types(self):
        """Enum types should be emitted correctly."""
        status = extract_type(self.content, 'Status')
        assert status is not None, 'Status enum type not found'
        assert "'ACTIVE'" in status
        assert "'INACTIVE'" in status
        assert "'PENDING'" in status

        priority = extract_type(self.content, 'Priority')
        assert priority is not None, 'Priority enum type not found'
        assert "'LOW'" in priority
        assert "'HIGH'" in priority
        assert "'CRITICAL'" in priority

    # ------------------------------------------------------------------
    # Variables types
    # ------------------------------------------------------------------
    def test_variables_types(self):
        """Variables types should be generated correctly."""
        vars_type = extract_type(self.content, 'UserProfileQueryVariables')
        assert vars_type is not None, 'UserProfileQueryVariables not found'
        norm = normalize(vars_type)
        assert 'userId: string' in norm

    # ------------------------------------------------------------------
    # Custom scalars
    # ------------------------------------------------------------------
    def test_custom_scalars(self):
        """Custom scalar mappings from config should be applied."""
        user_profile = extract_type(self.content, 'UserProfileQuery')
        assert user_profile is not None
        norm = normalize(user_profile)
        # DateTime is mapped to 'string' — createdAt should be string
        assert 'createdAt: string' in norm or 'createdAt?: string' in norm, (
            'DateTime scalar should map to string via config.'
        )

    # ------------------------------------------------------------------
    # Search result includes fragment fields (Bug 1 + Bug 2 interaction)
    # ------------------------------------------------------------------
    def test_search_post_includes_fragment_fields(self):
        """The Post branch of SearchContentQuery should include PostSummary fragment fields."""
        search = extract_type(self.content, 'SearchContentQuery')
        assert search is not None
        norm = normalize(search)
        # PostSummary fragment should contribute 'body' to the Post branch
        assert 'body: string' in norm, (
            'PostSummary fragment fields missing from Post branch of SearchContentQuery.'
        )
