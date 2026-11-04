#!/usr/bin/env perl
use strict;
use warnings;

die "usage: java_apply_bug.pl SOURCE ORIGINAL_CODE BUGGY_CODE\n" unless @ARGV == 3;
my ($source_path, $original_path, $buggy_path) = @ARGV;

sub read_bytes {
    my ($path) = @_;
    open my $handle, '<:raw', $path or die "cannot read $path: $!\n";
    local $/;
    my $content = <$handle>;
    close $handle or die "cannot close $path: $!\n";
    return defined($content) ? $content : '';
}

my $source = read_bytes($source_path);
my $original = read_bytes($original_path);
my $buggy = read_bytes($buggy_path);
die "original and buggy code must be non-empty and different\n"
    if $original eq '' || $buggy eq '' || $original eq $buggy;

my $count = 0;
my $offset = 0;
while (1) {
    my $position = index($source, $original, $offset);
    last if $position < 0;
    $count++;
    $offset = $position + length($original);
}
die "original code occurs $count times in $source_path (expected 1)\n" if $count != 1;

my $position = index($source, $original);
substr($source, $position, length($original), $buggy);
my $temporary = "$source_path.adverbug.tmp";
open my $output, '>:raw', $temporary or die "cannot write $temporary: $!\n";
print {$output} $source or die "cannot write $temporary: $!\n";
close $output or die "cannot close $temporary: $!\n";
rename $temporary, $source_path or die "cannot replace $source_path: $!\n";
print "applied buggy method to $source_path\n";
